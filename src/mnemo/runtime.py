from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from .errors import MnemoError, NotFoundError
from .ids import new_id
from .ledger import RunLedger
from .models import RunRequest, RunResult, ToolCallEnvelope, ToolResult
from .storage import StateStore
from .tools import ToolHarness, ToolRegistry, tool_specs_as_json_schema


class LocalAgentRuntime:
    """Deterministic local adapter for the Mnemo agent loop.

    The production adapter will call an LLM with provider-native tool calls.
    This local adapter keeps the same normalized tool-call boundary so schema,
    persistence, and RunLedger behavior can be tested without an API key.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry()

    def run(self, request: RunRequest) -> RunResult:
        store = StateStore(request.state_dir)
        store.initialize()
        ledger = RunLedger(store)
        harness = ToolHarness(store=store, ledger=ledger, registry=self.registry)

        conversation_id = self._resolve_conversation(store, request)
        mission_id = self._resolve_mission(store, conversation_id, request)
        run_id = store.create_run(conversation_id, mission_id, request.message)

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
        ledger.append(
            run_id,
            "prompt.assembled",
            {
                "mode": "full",
                "stable_prefix": ["mnemo_core", "tool_bundle"],
                "dynamic_tail": ["mission_checkpoint", "current_turn"],
                "tool_count": len(self.registry.specs()),
                "tools": [spec["name"] for spec in tool_specs_as_json_schema(self.registry.specs())],
            },
        )

        tool_calls = self._plan_local_tool_calls(request.message)
        tool_results: list[ToolResult] = []
        try:
            for call in tool_calls:
                tool_results.append(harness.execute(call, run_id=run_id, mission_id=mission_id))

            response = self._render_response(request.message, tool_results)
            checkpoint = self._checkpoint(store, mission_id, request.message, response, run_id, tool_results)
            store.update_mission_checkpoint(mission_id, checkpoint)
            ledger.append(run_id, "assistant.response", {"text": response})
            ledger.append(run_id, "run.completed", {"status": "completed"})
            store.complete_run(run_id, response)
            return RunResult(
                conversation_id=conversation_id,
                mission_id=mission_id,
                run_id=run_id,
                response=response,
                tool_results=tool_results,
            )
        except Exception as exc:
            response = f"Run failed: {exc}"
            ledger.append(run_id, "run.completed", {"status": "failed", "error": str(exc)})
            store.complete_run(run_id, response, status="failed")
            raise

    def _resolve_conversation(self, store: StateStore, request: RunRequest) -> str:
        if not request.conversation_id:
            return store.create_conversation(title=_short_title(request.message))
        if not store.get_conversation(request.conversation_id):
            raise NotFoundError(f"conversation not found: {request.conversation_id}")
        return request.conversation_id

    def _resolve_mission(self, store: StateStore, conversation_id: str, request: RunRequest) -> str:
        if request.mission_id:
            mission = store.get_mission(request.mission_id)
            if not mission:
                raise NotFoundError(f"mission not found: {request.mission_id}")
            if mission["conversation_id"] != conversation_id:
                raise MnemoError("mission does not belong to the selected conversation")
            return request.mission_id

        latest = store.latest_active_mission(conversation_id)
        if latest:
            return str(latest["id"])
        return store.create_mission(conversation_id, brief=_short_title(request.message, limit=120))

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

        for artifact in _extract_prefixed_values(message, ["artifact", "产物"]):
            calls.append(
                ToolCallEnvelope(
                    call_id=new_id("call"),
                    name="artifact_update",
                    arguments={"title": "Draft Artifact", "body": artifact, "kind": "markdown"},
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
            elif result.name == "artifact_update":
                parts.append(f"已更新产物 {result.result['artifact_id']}。")
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


def result_as_dict(result: RunResult) -> dict[str, Any]:
    return {
        "conversation_id": result.conversation_id,
        "mission_id": result.mission_id,
        "run_id": result.run_id,
        "response": result.response,
        "tool_results": [asdict(tool_result) for tool_result in result.tool_results],
    }
