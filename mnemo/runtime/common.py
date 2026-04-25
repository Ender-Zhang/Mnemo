from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from ..core.errors import MnemoError
from ..core.events import chat_event_as_dict, new_chat_event
from ..core.models import ChatEvent, ChatEventType, PromptMode, RunResult, ToolCallEnvelope, ToolResult
from ..tools import ToolRegistry
from .ledger import RunLedger

if TYPE_CHECKING:
    from ..storage import StateStore


EmitChatEvent = Callable[[ChatEventType, dict[str, Any] | None], ChatEvent]


def ensure_executable_prompt_mode(mode: PromptMode) -> None:
    if mode == "none":
        raise MnemoError("prompt mode 'none' is diagnostic-only and cannot execute user tasks")


def make_chat_event_emitter(
    *,
    ledger: RunLedger,
    run_id: str,
    conversation_id: str,
    mission_id: str,
) -> EmitChatEvent:
    def emit(event_type: ChatEventType, data: dict[str, Any] | None = None) -> ChatEvent:
        event = new_chat_event(
            event_type,
            run_id=run_id,
            conversation_id=conversation_id,
            mission_id=mission_id,
            data=data or {},
        )
        ledger.append(run_id, "chat.event", chat_event_as_dict(event))
        return event

    return emit


def action_card(registry: ToolRegistry, call: ToolCallEnvelope) -> dict[str, Any]:
    spec = registry.spec(call.name)
    return {
        "action_id": call.call_id,
        "title": call.name,
        "summary": spec.description,
        "risk": spec.risk,
        "provider": call.provider,
    }


def tool_result_summary(result: ToolResult) -> str:
    if result.summary:
        return result.summary
    if not result.ok:
        return result.error or "Tool call failed."
    if result.name == "memory_write_candidate":
        return "记忆候选已记录，等待后续学习流程评估。"
    if result.name == "memory_search":
        return f"找到 {len(result.result.get('matches', []))} 条候选。"
    if result.name == "recall_search":
        return f"找回 {len(result.result.get('items', []))} 条上下文。"
    if result.name == "working_note":
        return "工作笔记已记录。"
    if result.name == "artifact_update":
        return "产物已更新。"
    if result.name == "ask_user":
        return "需要用户确认。"
    return "工具调用已完成。"


def project_tool_result(result: ToolResult, emit: EmitChatEvent) -> Iterator[ChatEvent]:
    if result.evidence:
        yield emit(
            "source.attached",
            {
                "source": {
                    "source_id": result.call_id,
                    "kind": "tool_result",
                    "title": result.name,
                    "summary": tool_result_summary(result),
                    "evidence": result.evidence,
                }
            },
        )
    if not result.ok:
        return
    if result.name == "recall_search":
        yield emit(
            "recall.card",
            {
                "recall": {
                    "query": result.result.get("query") or "",
                    "scope": result.result.get("scope") or "all",
                    "count": result.result.get("count") or len(result.result.get("items", [])),
                    "items": result.result.get("items", []),
                }
            },
        )
    elif result.name == "memory_write_candidate":
        yield emit(
            "learning.chip",
            {
                "item": {
                    "item_id": result.result["candidate_id"],
                    "kind": "memory",
                    "status": "draft",
                    "summary": "可能学到一个偏好或事实。",
                }
            },
        )
    elif result.name == "artifact_update":
        yield emit(
            "artifact.card",
            {
                "artifact": {
                    "artifact_id": result.result["artifact_id"],
                    "title": result.result.get("title") or "Artifact",
                    "kind": result.result.get("kind") or "markdown",
                }
            },
        )
    elif result.name == "ask_user":
        decision = result.result.get("decision") or {}
        yield emit(
            "decision.card",
            {
                "decision": {
                    "item_id": decision.get("item_id"),
                    "question": decision.get("question") or "Decision required",
                    "reason": decision.get("reason") or "",
                    "status": decision.get("status") or "open",
                    "options": decision.get("options") or ["accepted", "rejected", "ignored"],
                }
            },
        )


def result_as_dict(result: RunResult) -> dict[str, Any]:
    return {
        "conversation_id": result.conversation_id,
        "mission_id": result.mission_id,
        "run_id": result.run_id,
        "response": result.response,
        "tool_results": [asdict(tool_result) for tool_result in result.tool_results],
    }


def run_result_from_dict(value: dict[str, Any]) -> RunResult:
    return RunResult(
        conversation_id=value["conversation_id"],
        mission_id=value["mission_id"],
        run_id=value["run_id"],
        response=value["response"],
        tool_results=[
            ToolResult(
                call_id=item["call_id"],
                name=item["name"],
                ok=item["ok"],
                result=item.get("result") or {},
                error=item.get("error"),
            )
            for item in value.get("tool_results", [])
        ],
    )


def cancellation_result(
    *,
    store: "StateStore",
    ledger: RunLedger,
    emit: EmitChatEvent,
    run_id: str,
    conversation_id: str,
    mission_id: str,
    tool_results: list[ToolResult],
    reason: str = "cancelled",
) -> Iterator[ChatEvent]:
    response = "已取消。"
    yield emit("status.updated", {"text": response, "tone": "cancelled"})
    yield emit("assistant.message", {"text": response, "final": True})
    ledger.append(run_id, "run.completed", {"status": "cancelled", "reason": reason})
    store.complete_run(run_id, response, status="cancelled")
    result = RunResult(
        conversation_id=conversation_id,
        mission_id=mission_id,
        run_id=run_id,
        response=response,
        tool_results=tool_results,
    )
    yield emit("run.completed", {"status": "cancelled", "result": result_as_dict(result)})
