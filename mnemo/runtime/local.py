from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from ..core.errors import MnemoError
from ..core.ids import new_id
from ..core.models import ChatEvent, RunRequest, RunResult, ToolCallEnvelope, ToolExecutionPolicy, ToolResult
from ..memory import MemoryEngine
from ..prompt import PromptAssembler, load_prompt_bootstrap
from ..skills import SkillService, default_skill_roots
from ..storage import StateStore
from ..tools import ToolHarness, ToolRegistry, tool_specs_as_json_schema
from .common import (
    action_card,
    build_tool_bundle,
    cancellation_result,
    ensure_executable_prompt_mode,
    make_chat_event_emitter,
    project_tool_result,
    result_as_dict,
    run_result_from_dict,
    tool_result_summary,
)
from .ledger import RunLedger
from .state import resolve_conversation, resolve_mission


class LocalAgentRuntime:
    """Deterministic local adapter for the Mnemo agent loop.

    The production adapter will call an LLM with provider-native tool calls.
    This local adapter keeps the same normalized tool-call boundary so schema,
    persistence, and RunLedger behavior can be tested without an API key.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry

    def run(self, request: RunRequest) -> RunResult:
        final_result: RunResult | None = None
        for event in self.stream(request):
            if event.type == "run.completed":
                final_result = run_result_from_dict(event.data["result"])
        if final_result is None:
            raise MnemoError("run did not produce a completion event")
        return final_result

    def stream(self, request: RunRequest) -> Iterator[ChatEvent]:
        ensure_executable_prompt_mode(request.prompt_mode)
        store = StateStore(request.state_dir)
        store.initialize()
        ledger = RunLedger(store)
        registry = self.registry or ToolRegistry.from_store(store)
        if self.registry is not None:
            registry.load_generated_tools(store.list_generated_tools(status="active", limit=100))

        conversation_id = resolve_conversation(store, request, title=_short_title(request.message))
        mission_id = resolve_mission(store, conversation_id, request, brief=_short_title(request.message, limit=120))
        run_id = store.create_run(conversation_id, mission_id, request.message)
        tool_bundle = build_tool_bundle(registry, prompt_mode=request.prompt_mode, provider_name="local")
        harness = ToolHarness(
            store=store,
            ledger=ledger,
            registry=registry,
            policy=ToolExecutionPolicy(allowed_tools=tool_bundle.tool_names),
            workspace_root=request.workspace_root,
        )
        emit = make_chat_event_emitter(
            ledger=ledger,
            run_id=run_id,
            conversation_id=conversation_id,
            mission_id=mission_id,
        )

        ledger.append(
            run_id,
            "request.received",
            {
                "conversation_id": conversation_id,
                "mission_id": mission_id,
                "message": request.message,
                "source": "cli",
            },
        )
        yield emit(
            "turn.started",
            {
                "turn_id": run_id,
                "input_summary": _short_title(request.message, limit=100),
            },
        )
        yield emit(
            "conversation.hydrated",
            {
                "summary": "已恢复当前对话和任务状态。",
            },
        )
        mission = store.get_mission(mission_id) or {}
        memory_engine = MemoryEngine(store)
        bootstrap = load_prompt_bootstrap(request.state_dir, workspace_root=request.workspace_root)
        assembled_prompt = PromptAssembler().assemble(
            request.message,
            mission=mission,
            tool_specs=tool_bundle.specs,
            soul_context=bootstrap.soul,
            workspace_context=bootstrap.workspace,
            memory_snapshot=memory_engine.load_l1_snapshot(),
            memory_cards=memory_engine.context_cards(request.message, limit=5),
            skill_cards=SkillService(store, roots=default_skill_roots(request.state_dir)).context_cards(limit=12),
            mode=request.prompt_mode,
        )
        ledger.append(
            run_id,
            "prompt.assembled",
            {
                **assembled_prompt.metadata(),
                "tool_bundle": tool_bundle.metadata(),
                "tool_count": len(tool_bundle.tool_names),
                "tools": [spec["name"] for spec in tool_specs_as_json_schema(list(tool_bundle.specs))],
            },
        )
        yield emit("status.updated", {"text": "正在处理请求。", "tone": "working"})

        tool_calls = self._plan_local_tool_calls(request.message)
        tool_results: list[ToolResult] = []
        try:
            for call in tool_calls:
                if store.is_run_cancelled(run_id):
                    yield from cancellation_result(
                        store=store,
                        ledger=ledger,
                        emit=emit,
                        run_id=run_id,
                        conversation_id=conversation_id,
                        mission_id=mission_id,
                        tool_results=tool_results,
                    )
                    return
                action = action_card(registry, call)
                yield emit("action.queued", {"action": action, "provider_call_id": call.call_id})
                yield emit("action.started", {"action": action})
                result = harness.execute(call, run_id=run_id, mission_id=mission_id)
                tool_results.append(result)
                yield emit(
                    "action.completed",
                    {
                        "action_id": call.call_id,
                        "outcome": "success" if result.ok else "failed",
                        "summary": tool_result_summary(result),
                        "tool_name": result.name,
                    },
                )
                for projected in project_tool_result(result, emit):
                    yield projected
                if store.is_run_cancelled(run_id):
                    yield from cancellation_result(
                        store=store,
                        ledger=ledger,
                        emit=emit,
                        run_id=run_id,
                        conversation_id=conversation_id,
                        mission_id=mission_id,
                        tool_results=tool_results,
                    )
                    return

            response = self._render_response(request.message, tool_results)
            checkpoint = self._checkpoint(store, mission_id, request.message, response, run_id, tool_results)
            store.update_mission_checkpoint(mission_id, checkpoint)
            if response:
                yield emit("assistant.delta", {"text": response})
                yield emit("assistant.message", {"text": response, "final": True})
            ledger.append(run_id, "assistant.response", {"text": response})
            ledger.append(run_id, "run.completed", {"status": "completed"})
            store.complete_run(run_id, response)
            result = RunResult(
                conversation_id=conversation_id,
                mission_id=mission_id,
                run_id=run_id,
                response=response,
                tool_results=tool_results,
            )
            yield emit("run.completed", {"status": "completed", "result": result_as_dict(result)})
        except Exception as exc:
            response = f"Run failed: {exc}"
            yield emit("run.error", {"error": str(exc)})
            ledger.append(run_id, "run.completed", {"status": "failed", "error": str(exc)})
            store.complete_run(run_id, response, status="failed")
            raise

    def _plan_local_tool_calls(self, message: str) -> list[ToolCallEnvelope]:
        calls: list[ToolCallEnvelope] = []
        for claim in _extract_prefixed_values(message, ["remember", "记住", "请记住"]):
            calls.append(
                ToolCallEnvelope(
                    call_id=new_id("call"),
                    name="memory_write_candidate",
                    arguments={
                        "claim": claim,
                        "dimension": "user_preference",
                        "scope": "global",
                        "confidence": 0.72,
                        "evidence": [{"kind": "user_message", "text": message}],
                    },
                    risk="write",
                )
            )

        for note in _extract_prefixed_values(message, ["note", "工作笔记"]):
            calls.append(
                ToolCallEnvelope(
                    call_id=new_id("call"),
                    name="working_note",
                    arguments={"content": note},
                    risk="write",
                )
            )

        for query in _extract_prefixed_values(message, ["search", "搜索记忆"]):
            calls.append(
                ToolCallEnvelope(
                    call_id=new_id("call"),
                    name="memory_search",
                    arguments={"query": query, "limit": 5},
                    risk="read",
                )
            )

        for query in _extract_prefixed_values(message, ["recall", "找回"]):
            calls.append(
                ToolCallEnvelope(
                    call_id=new_id("call"),
                    name="recall_search",
                    arguments={"query": query, "limit": 8, "scope": "all"},
                    risk="read",
                )
            )

        for artifact in _extract_prefixed_values(message, ["artifact", "产物"]):
            calls.append(
                ToolCallEnvelope(
                    call_id=new_id("call"),
                    name="artifact_update",
                    arguments={"title": "Draft Artifact", "body": artifact, "kind": "markdown"},
                    risk="write",
                )
            )

        for question in _extract_prefixed_values(message, ["ask", "decision", "确认"]):
            calls.append(
                ToolCallEnvelope(
                    call_id=new_id("call"),
                    name="ask_user",
                    arguments={"question": question, "reason": "Local deterministic decision request."},
                    risk="write",
                )
            )

        return calls

    def _render_response(self, message: str, tool_results: list[ToolResult]) -> str:
        if not tool_results:
            return "已创建一次 Mnemo 运行，并保留了可回放账本。"

        parts: list[str] = []
        for result in tool_results:
            if not result.ok:
                parts.append(f"{result.name} failed: {result.error}")
                continue
            if result.name == "memory_write_candidate":
                parts.append(f"已写入记忆候选 {result.result['candidate_id']}。")
            elif result.name == "working_note":
                parts.append(f"已写入工作笔记 {result.result['note_id']}。")
            elif result.name == "memory_search":
                count = len(result.result.get("matches", []))
                parts.append(f"找到 {count} 条记忆候选。")
            elif result.name == "recall_search":
                count = len(result.result.get("items", []))
                parts.append(f"找回 {count} 条可继续的上下文。")
            elif result.name == "artifact_update":
                parts.append(f"已更新产物 {result.result['artifact_id']}。")
            elif result.name == "ask_user":
                decision = result.result.get("decision") or {}
                parts.append(f"已创建确认项 {decision.get('item_id')}。")
            else:
                parts.append(f"{result.name} completed.")
        return " ".join(parts)

    def _checkpoint(
        self,
        store: StateStore,
        mission_id: str,
        user_message: str,
        response: str,
        run_id: str,
        tool_results: list[ToolResult],
    ) -> dict[str, Any]:
        mission = store.get_mission(mission_id) or {}
        checkpoint = dict(mission.get("checkpoint") or {})
        checkpoint.update(
            {
                "goal": mission.get("brief") or _short_title(user_message, limit=120),
                "status": "active",
                "last_user_message": user_message,
                "last_response": response,
                "last_run_id": run_id,
                "last_tools": [
                    {
                        "name": result.name,
                        "ok": result.ok,
                        "result": result.result,
                        "error": result.error,
                    }
                    for result in tool_results
                ],
            }
        )
        return checkpoint


def run_local(request: RunRequest) -> RunResult:
    return LocalAgentRuntime().run(request)


def stream_local(request: RunRequest) -> Iterator[ChatEvent]:
    return LocalAgentRuntime().stream(request)


def _short_title(text: str, limit: int = 60) -> str:
    compact = " ".join(text.strip().split())
    if not compact:
        return "Untitled Mission"
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _extract_prefixed_values(message: str, prefixes: list[str]) -> list[str]:
    values: list[str] = []
    for prefix in prefixes:
        pattern = re.compile(rf"(?:^|\n)\s*{re.escape(prefix)}\s*[:：,，]?\s*(.+)", re.IGNORECASE)
        for match in pattern.finditer(message):
            value = match.group(1).strip()
            if value:
                values.append(value)
    return values
