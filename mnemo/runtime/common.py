from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from ..core.errors import MnemoError
from ..core.events import chat_event_as_dict, new_chat_event
from ..core.models import ChatEvent, ChatEventType, PromptMode, RunResult, ToolCallEnvelope, ToolResult
from ..providers import ProviderCapabilities, provider_capabilities
from ..tools import ToolBundle, ToolRegistry
from .ledger import RunLedger

if TYPE_CHECKING:
    from ..storage import StateStore


EmitChatEvent = Callable[[ChatEventType, dict[str, Any] | None], ChatEvent]


def ensure_executable_prompt_mode(mode: PromptMode) -> None:
    if mode == "none":
        raise MnemoError("prompt mode 'none' is diagnostic-only and cannot execute user tasks")


def build_tool_bundle(
    registry: ToolRegistry,
    *,
    prompt_mode: PromptMode,
    capabilities: ProviderCapabilities | None = None,
    provider_name: str | None = None,
) -> ToolBundle:
    resolved = capabilities or provider_capabilities(provider_name or "local")
    return registry.tool_bundle(
        profile=_tool_profile_for_prompt_mode(prompt_mode),
        provider_adapter_version=resolved.adapter_version,
    )


def expand_tool_bundle_from_result(
    registry: ToolRegistry,
    bundle: ToolBundle,
    result: ToolResult,
) -> ToolBundle | None:
    if result.name != "tool_expand_schema" or not result.ok:
        return None
    expanded = result.result.get("expanded_tool_names")
    if not isinstance(expanded, list) or not expanded:
        return None
    selected = [*bundle.tool_names]
    for name in expanded:
        if isinstance(name, str) and name not in selected:
            selected.append(name)
    return registry.tool_bundle(
        profile=bundle.profile,
        provider_adapter_version=bundle.provider_adapter_version,
        selected_tool_names=selected,
        epoch=bundle.epoch + 1,
        cache_bust_reason="lazy_schema_expansion",
    )


def _tool_profile_for_prompt_mode(mode: PromptMode) -> str:
    if mode == "full":
        return "full.v1"
    if mode == "minimal":
        return "minimal.v1"
    if mode == "capsule":
        return "capsule.v1"
    return "none.v1"


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
        decision = result.result.get("decision")
        if isinstance(decision, dict) and decision.get("item_id"):
            return "需要用户确认。"
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
        decision = _decision_payload(result)
        if decision:
            yield emit("decision.card", {"decision": decision})
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
        yield emit("learning.chip", {"item": _memory_learning_item(result)})
    elif result.name in {"skill_propose_candidate", "tool_propose_candidate", "eval_propose_case"}:
        item = _learning_candidate_item(result)
        if item:
            yield emit("learning.chip", {"item": item})
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
        decision = _decision_payload(result)
        if decision:
            yield emit("decision.card", {"decision": decision})


def _learning_candidate_item(result: ToolResult) -> dict[str, Any] | None:
    if result.name == "skill_propose_candidate":
        return {
            "item_id": result.result.get("skill_id"),
            "kind": "skill",
            "status": result.result.get("status") or "draft",
            "summary": "可能学到一个可复用技能。",
        }
    if result.name == "tool_propose_candidate":
        return {
            "item_id": result.result.get("candidate_id"),
            "kind": "tool",
            "status": result.result.get("status") or "draft",
            "summary": "可能沉淀一个可复用工具。",
        }
    if result.name == "eval_propose_case":
        return {
            "item_id": result.result.get("case_id"),
            "kind": "eval_case",
            "status": result.result.get("status") or "draft",
            "summary": "可能沉淀一个回放评测用例。",
        }
    return None


def _memory_learning_item(result: ToolResult) -> dict[str, Any]:
    status = str(result.result.get("status") or "draft")
    safety = result.result.get("safety") if isinstance(result.result.get("safety"), dict) else {}
    requires_confirmation = status.startswith("needs_review") or bool(safety.get("requires_review"))
    item: dict[str, Any] = {
        "item_id": result.result["candidate_id"],
        "kind": "memory",
        "status": status,
        "summary": "这条学习需要你确认后才会长期记住。" if requires_confirmation else "可能学到一个偏好或事实。",
        "requires_confirmation": requires_confirmation,
    }
    if safety.get("risk"):
        item["risk"] = safety["risk"]
    if safety.get("review_reason"):
        item["confirmation_reason"] = safety["review_reason"]
    return item


def _decision_payload(result: ToolResult) -> dict[str, Any] | None:
    decision = result.result.get("decision")
    if not isinstance(decision, dict):
        return None
    item_id = decision.get("item_id")
    if not item_id:
        return None
    return {
        "item_id": item_id,
        "question": decision.get("question") or "Decision required",
        "reason": decision.get("reason") or "",
        "status": decision.get("status") or "open",
        "options": decision.get("options") or ["accepted", "rejected", "ignored"],
        "action_type": decision.get("action_type"),
        "tool_name": decision.get("tool_name"),
        "risk": decision.get("risk"),
    }


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
