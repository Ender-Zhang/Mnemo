from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.config import DEFAULT_STATE_DIR
from ..core.models import PromptMode, RunRequest, ToolResult
from ..evals import EvalHarness, replay_summary
from ..memory import MemoryEngine
from ..providers import provider_capabilities
from ..prompt import PromptAssembler, load_prompt_bootstrap
from ..runtime import run_local
from ..runtime.common import build_tool_bundle
from ..runtime.ledger import RunLedger
from ..skills import SkillService, default_skill_roots
from ..storage import StateStore
from ..tools import ToolRegistry, compact_tool_result


class MnemoClient:
    """Reference in-process SDK for the MnemoCore API."""

    def __init__(
        self,
        *,
        state_dir: str | Path = DEFAULT_STATE_DIR,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.state_dir = str(state_dir)
        self.workspace_root = str(workspace_root) if workspace_root is not None else None

    def context(
        self,
        intent: str = "",
        *,
        agent_role: str = "general",
        budget_tokens: int = 4000,
        include_associations: bool = True,
        prompt_mode: PromptMode = "full",
    ) -> dict[str, Any]:
        _require_context_prompt_mode(prompt_mode)
        store = self._store()
        memory = MemoryEngine(store)
        registry = ToolRegistry.from_store(store)
        capabilities = provider_capabilities("local")
        tool_bundle = build_tool_bundle(registry, prompt_mode=prompt_mode, capabilities=capabilities)
        bootstrap = load_prompt_bootstrap(self.state_dir, workspace_root=self.workspace_root)
        query = _context_query(intent, agent_role)
        memory_cards = memory.context_cards(query, limit=5, search_scope="all") if include_associations and query else []
        skill_cards = SkillService(store, roots=default_skill_roots(self.state_dir)).context_cards(limit=12)
        assembled = PromptAssembler().assemble(
            query,
            tool_specs=tool_bundle.specs,
            soul_context=bootstrap.soul,
            workspace_context=bootstrap.workspace,
            memory_snapshot=memory.load_l1_snapshot(),
            memory_cards=memory_cards,
            skill_cards=skill_cards,
            token_budget=max(512, int(budget_tokens)),
            mode=prompt_mode,
        )
        return {
            "kind": "context_block",
            "version": "mnemo.context.v1",
            "intent": intent,
            "agent_role": agent_role,
            "prompt_mode": prompt_mode,
            "messages": assembled.messages(),
            "text": _messages_text(assembled.messages()),
            "metadata": assembled.metadata(),
            "tool_bundle": tool_bundle.metadata(),
            "cards": {
                "memory": memory_cards,
                "skills": skill_cards,
            },
        }

    def recall(
        self,
        seed: str,
        *,
        depth: int = 2,
        context: str = "",
        limit: int = 8,
    ) -> dict[str, Any]:
        store = self._store()
        query = _recall_query(seed, context)
        bounded_depth = max(1, min(4, int(depth)))
        bounded_limit = max(1, min(20, int(limit)))
        result = MemoryEngine(store).search_with_plan(query, limit=bounded_limit, search_scope="all")
        return {
            "kind": "associative_cluster",
            "version": "mnemo.recall.v1",
            "seed": seed,
            "context": context,
            "depth": bounded_depth,
            "query_plan": result["query_plan"],
            "items": [_recall_item(item) for item in result["matches"][:bounded_limit]],
        }

    def run(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        mission_id: str | None = None,
        prompt_mode: PromptMode = "full",
    ) -> dict[str, Any]:
        result = run_local(
            RunRequest(
                message=message,
                state_dir=self.state_dir,
                conversation_id=conversation_id,
                mission_id=mission_id,
                workspace_root=self.workspace_root,
                prompt_mode=prompt_mode,
            )
        )
        ledger = RunLedger(self._store())
        events = ledger.chat_events(result.run_id)
        return {
            "conversation_id": result.conversation_id,
            "mission_id": result.mission_id,
            "run_id": result.run_id,
            "response": result.response,
            "tool_summary": [_compact_tool(tool) for tool in result.tool_results],
            "event_summary": _event_summary(events),
        }

    def replay(self, run_id: str) -> dict[str, Any]:
        return replay_summary(self.state_dir, run_id)

    def evaluate(self, suite: str = "smoke") -> dict[str, Any]:
        return EvalHarness(state_dir=self.state_dir).run_suite(suite).as_dict()

    def _store(self) -> StateStore:
        store = StateStore(self.state_dir)
        store.initialize()
        return store


def _context_query(intent: str, agent_role: str) -> str:
    parts = []
    if agent_role.strip():
        parts.append(f"agent_role: {agent_role.strip()}")
    if intent.strip():
        parts.append(f"intent: {intent.strip()}")
    return "\n".join(parts) or "agent_role: general"


def _require_context_prompt_mode(prompt_mode: PromptMode) -> None:
    if prompt_mode == "none":
        raise ValueError("prompt mode 'none' is diagnostic-only and cannot produce an executable context block")


def _recall_query(seed: str, context: str) -> str:
    seed = seed.strip()
    if not seed:
        raise ValueError("recall seed is required")
    return " ".join(part for part in [seed, context.strip()] if part)


def _messages_text(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(f"<{message['role']}>\n{message['content']}" for message in messages)


def _recall_item(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") == "session_message":
        return {
            "kind": "session_message",
            "item_id": item.get("id"),
            "title": f"{item.get('role', 'message')} message",
            "summary": item.get("snippet", ""),
            "conversation_id": item.get("conversation_id"),
            "mission_id": item.get("mission_id"),
            "run_id": item.get("run_id"),
            "message_id": item.get("message_id") or item.get("id"),
            "created_at": item.get("created_at"),
        }
    if item.get("type") in {"page", "linked_page"}:
        result = {
            "kind": item.get("type"),
            "item_id": item.get("id"),
            "title": item.get("title") or "Memory page",
            "summary": _compact_text(item.get("content", "")),
            "confidence": item.get("confidence"),
            "status": item.get("status"),
        }
        if item.get("type") == "linked_page":
            result["relation"] = item.get("relation")
            result["linked_from"] = item.get("linked_from")
        return result
    return {
        "kind": "candidate",
        "item_id": item.get("id"),
        "title": item.get("dimension") or "Memory candidate",
        "summary": _compact_text(item.get("claim", "")),
        "confidence": item.get("confidence"),
        "status": item.get("status"),
    }


def _compact_tool(result: ToolResult) -> dict[str, Any]:
    compact = compact_tool_result(result)
    compact["call_id"] = result.call_id
    return compact


def _event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    event_types = [str(event.get("type") or "") for event in events]
    return {
        "chat_event_count": len(event_types),
        "event_types": event_types,
    }


def _compact_text(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."
