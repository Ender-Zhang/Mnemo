from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.config import DEFAULT_STATE_DIR
from ..core.models import PromptMode, RunRequest, ToolResult
from ..core.workspace import resolve_workspace_root
from ..evals import EvalHarness, replay_summary
from ..memory import MemoryEngine
from ..providers import provider_capabilities
from ..prompt import PromptAssembler, load_prompt_bootstrap
from ..runtime import (
    ExternalRunRequest,
    ScheduleService,
    build_context_capsule,
    run_external,
    run_local,
    scheduled_item_stats,
    scheduled_prompt_items,
)
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
        resolved_workspace = resolve_workspace_root(workspace_root, self.state_dir)
        resolved_workspace.mkdir(parents=True, exist_ok=True)
        self.workspace_root = str(resolved_workspace)

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
            scheduled_items=scheduled_prompt_items(store),
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

    def capsule(
        self,
        task: str,
        *,
        runtime: str = "external",
        agent_type: str = "general",
        requested_pages: list[str] | tuple[str, ...] | None = None,
        allowed_pages: list[str] | tuple[str, ...] | None = None,
        conversation_id: str | None = None,
        mission_id: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        return build_context_capsule(
            self.state_dir,
            task,
            runtime=runtime,
            agent_type=agent_type,
            requested_pages=requested_pages,
            allowed_pages=allowed_pages,
            conversation_id=conversation_id,
            mission_id=mission_id,
            limit=limit,
        )

    def external_run(
        self,
        task: str,
        *,
        command: list[str] | tuple[str, ...],
        runtime: str = "external-command",
        agent_type: str = "general",
        requested_pages: list[str] | tuple[str, ...] | None = None,
        allowed_pages: list[str] | tuple[str, ...] | None = None,
        conversation_id: str | None = None,
        mission_id: str | None = None,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        return run_external(
            ExternalRunRequest(
                task=task,
                state_dir=self.state_dir,
                command=command,
                runtime=runtime,
                agent_type=agent_type,
                requested_pages=requested_pages,
                allowed_pages=allowed_pages,
                conversation_id=conversation_id,
                mission_id=mission_id,
                workspace_root=self.workspace_root,
                timeout_s=timeout_s,
            )
        )

    def schedule_dream(
        self,
        *,
        schedule: str = "daily",
        title: str | None = None,
        next_run_at: float | str | None = None,
        limit: int = 20,
        min_confidence: float = 0.7,
        source: str = "sdk",
    ) -> dict[str, Any]:
        item = ScheduleService(self.state_dir).add_dream(
            title=title,
            schedule=schedule,
            source=source,
            next_run_at=next_run_at,
            limit=limit,
            min_confidence=min_confidence,
            metadata={"source": source},
        )
        return {
            "kind": "scheduled_item",
            "version": "mnemo.schedule_dream.v1",
            "item": item,
        }

    def schedule_watch(
        self,
        target: str,
        *,
        instruction: str | None = None,
        schedule: str = "daily",
        next_run_at: float | str | None = None,
        source: str = "sdk",
    ) -> dict[str, Any]:
        item = ScheduleService(self.state_dir).add_watch(
            target=target,
            instruction=instruction if instruction is not None else target,
            schedule=schedule,
            source=source,
            next_run_at=next_run_at,
            metadata={"source": source},
        )
        return {
            "kind": "scheduled_item",
            "version": "mnemo.schedule_watch.v1",
            "item": item,
        }

    def schedule_cron(
        self,
        message: str,
        *,
        schedule: str = "once",
        title: str | None = None,
        next_run_at: float | str | None = None,
        source: str = "sdk",
    ) -> dict[str, Any]:
        item = ScheduleService(self.state_dir).add_cron(
            title=title,
            message=message,
            schedule=schedule,
            source=source,
            next_run_at=next_run_at,
            metadata={"source": source},
        )
        return {
            "kind": "scheduled_item",
            "version": "mnemo.schedule_cron.v1",
            "item": item,
        }

    def runtime_status(self, *, limit: int = 10) -> dict[str, Any]:
        bounded_limit = max(1, min(50, int(limit)))
        store = self._store()
        inbox_items = store.list_inbox_items(status="open", limit=bounded_limit)
        generated_tools = store.list_generated_tools(status=None, limit=100)
        from ..runtime.proactive import proactive_status

        return {
            "kind": "runtime_status",
            "version": "mnemo.runtime_status.v1",
            "queue": store.queue_stats(),
            "recent_runs": [
                _run_status_card(run)
                for run in store.list_runs(limit=bounded_limit)
            ],
            "open_inbox": {
                "count": len(inbox_items),
                "items": [_inbox_card(item) for item in inbox_items],
            },
            "generated_tools": _status_counts(generated_tools),
            "scheduled": scheduled_item_stats(store),
            "proactive": proactive_status(self.state_dir),
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

    def evaluate(
        self,
        suite: str = "smoke",
        *,
        variants: list[str] | tuple[str, ...] | None = None,
        release_gate: bool = False,
    ) -> dict[str, Any]:
        harness = EvalHarness(state_dir=self.state_dir)
        if release_gate:
            if variants:
                raise ValueError("release_gate cannot be combined with variants")
            return harness.run_release_report().as_dict()
        if variants:
            return harness.run_variant_report(suite, variants=variants).as_dict()
        return harness.run_suite(suite).as_dict()

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


def _run_status_card(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run.get("id"),
        "conversation_id": run.get("conversation_id"),
        "mission_id": run.get("mission_id"),
        "status": run.get("status"),
        "input": _compact_text(
            run.get("input_preview") or run.get("input_text"),
            limit=120,
        ),
        "created_at": run.get("created_at"),
        "completed_at": run.get("completed_at"),
    }


def _inbox_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "priority": item.get("priority"),
        "category": item.get("category"),
        "title": item.get("title"),
        "action_type": item.get("action_type"),
        "source_run_id": item.get("source_run_id"),
        "created_at": item.get("created_at"),
    }


def _status_counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(items), "counts": counts}


def _compact_text(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."
