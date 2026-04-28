from __future__ import annotations

from typing import Any

from ..core.jsonutil import dumps
from ..core.models import ToolResult
from ..storage import StateStore
from ..tools.registry import LEARNING_REFLECTION_TOOL_NAMES, LEARNING_TOOL_PROFILE, ToolRegistry, compact_tool_result


LEARNING_PACKET_VERSION = "mnemo.learning_packet.v1"
LEARNING_REFLECTION_SYSTEM = """You are Mnemo's after-turn learning triage.
The user-facing answer has already been sent. Do not reply to the user.
Review the compact learning packet and decide whether anything should evolve.
You may call 0..N provider-native tools. Candidates may be mixed: memory, skill, tool, eval case, or discard.
Use only evidence visible in the packet. Do not invent facts. Do not duplicate candidates already created in tool_results.
Prefer no tool call when there is no durable learning signal."""

LEARNING_CANDIDATE_TOOLS = {
    "memory_write_candidate",
    "skill_propose_candidate",
    "tool_propose_candidate",
    "eval_propose_case",
}
REFLECTION_MIN_STRUCTURED_TOOL_RESULTS = 3
LEARNING_DEBT_PACKET_VERSION = "mnemo.learning_debt_packet.v1"
LEARNING_DEBT_MIN_RUNS = 5
LEARNING_DEBT_MAX_RUNS = 8
LEARNING_DEBT_SCAN_LIMIT = 24


def build_learning_packet(
    store: StateStore,
    run_id: str,
    *,
    response: str | None = None,
    tool_results: list[ToolResult] | None = None,
    text_limit: int = 1800,
    max_tools: int = 12,
) -> dict[str, Any]:
    run = store.get_run(run_id) or {}
    mission = store.get_mission(str(run.get("mission_id") or "")) if run.get("mission_id") else None
    compact_tools = [
        _compact_tool_result(index, result)
        for index, result in enumerate((tool_results or [])[:max_tools])
    ]
    existing_candidates = [
        item
        for item in compact_tools
        if _tool_result_has_learning_signal(item)
    ]
    return {
        "kind": "learning_packet",
        "version": LEARNING_PACKET_VERSION,
        "run": {
            "run_id": run_id,
            "conversation_id": run.get("conversation_id"),
            "mission_id": run.get("mission_id"),
            "status": run.get("status"),
        },
        "mission": {
            "brief": _clip(str((mission or {}).get("brief") or ""), 240),
            "status": (mission or {}).get("status"),
        },
        "turn": {
            "user_message": _clip(str(run.get("input_text") or ""), text_limit),
            "assistant_response": _clip(str(response if response is not None else run.get("output_text") or ""), text_limit),
        },
        "tool_results": compact_tools,
        "existing_learning_candidates": existing_candidates,
        "available_candidate_tools": list(LEARNING_REFLECTION_TOOL_NAMES),
        "instructions": [
            "Call candidate tools only when the packet contains durable evidence.",
            "A single packet may produce several candidate types or none.",
            "Use compact evidence objects that reference this run or tool result index.",
        ],
    }


def should_reflect_on_learning_packet(packet: dict[str, Any]) -> tuple[bool, str]:
    """Return whether a packet is worth a provider learning-reflection call."""

    if packet.get("kind") == "learning_debt_packet":
        runs = packet.get("runs")
        if isinstance(runs, list) and runs:
            return True, "learning_debt"
        return False, "empty_learning_debt"
    if packet.get("existing_learning_candidates"):
        return True, "existing_candidates"
    tool_results = packet.get("tool_results")
    if not isinstance(tool_results, list):
        return False, "no_structured_signal"
    structured_tool_count = sum(1 for item in tool_results if _is_main_turn_tool_result(item))
    if structured_tool_count >= REFLECTION_MIN_STRUCTURED_TOOL_RESULTS:
        return True, "structured_tool_threshold"
    return False, "insufficient_structured_signal"


def learning_reflection_messages(packet: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": LEARNING_REFLECTION_SYSTEM},
        {"role": "user", "content": "<learning_packet>\n" + dumps(packet) + "\n</learning_packet>"},
    ]


def build_learning_tool_bundle(
    registry: ToolRegistry,
    *,
    provider_adapter_version: str,
    epoch: int,
):
    return registry.tool_bundle(
        profile=LEARNING_TOOL_PROFILE,
        provider_adapter_version=provider_adapter_version,
        epoch=epoch,
        cache_bust_reason="after_turn_learning",
    )


def build_learning_debt_packet(
    store: StateStore,
    run_id: str,
    *,
    min_runs: int = LEARNING_DEBT_MIN_RUNS,
    max_runs: int = LEARNING_DEBT_MAX_RUNS,
    scan_limit: int = LEARNING_DEBT_SCAN_LIMIT,
    text_limit: int = 500,
) -> tuple[dict[str, Any] | None, str]:
    """Build a compact multi-run packet when recent turns accrued learning debt.

    This uses only structural run/event signals. The model still decides whether
    any memory, skill, tool, or eval candidate should be created.
    """

    current = store.get_run(run_id)
    if not current:
        return None, "missing_run"
    conversation_id = current.get("conversation_id")
    recent_runs = store.list_runs(
        status="completed",
        conversation_id=str(conversation_id) if conversation_id else None,
        limit=max(max_runs, scan_limit),
    )
    segment: list[dict[str, Any]] = []
    barrier: str | None = None
    for run in recent_runs:
        events = store.get_run_events(str(run["id"]))
        if _run_has_learning_candidate(events):
            barrier = "recent_learning_candidate"
            break
        if _run_has_learning_debt_review(events):
            barrier = "recent_debt_review"
            break
        segment.append(run)
        if len(segment) >= max_runs:
            break

    if len(segment) < max(1, int(min_runs)):
        return None, barrier or "insufficient_debt_runs"

    ordered_runs = list(reversed(segment[: max(1, int(max_runs))]))
    compact_runs = [
        _compact_debt_run(index, run, store.get_run_events(str(run["id"])), text_limit=text_limit)
        for index, run in enumerate(ordered_runs)
    ]
    return (
        {
            "kind": "learning_debt_packet",
            "version": LEARNING_DEBT_PACKET_VERSION,
            "trigger": {
                "current_run_id": run_id,
                "conversation_id": conversation_id,
                "min_runs": max(1, int(min_runs)),
                "max_runs": max(1, int(max_runs)),
                "reason": "recent_completed_runs_without_learning_candidates",
            },
            "runs": compact_runs,
            "available_candidate_tools": list(LEARNING_REFLECTION_TOOL_NAMES),
            "instructions": [
                "Review these recent completed turns for durable learning signals missed by per-turn reflection.",
                "Call 0..N candidate tools only when the compact traces contain evidence.",
                "Use evidence objects that reference run_id, run_index, or tool_result_index.",
                "Prefer no tool call when the turns are ordinary chat or contain no reusable preference, skill, tool, or eval signal.",
            ],
        },
        "learning_debt",
    )


def _compact_tool_result(index: int, result: ToolResult) -> dict[str, Any]:
    compact = compact_tool_result(result)
    compact["index"] = index
    compact["call_id"] = result.call_id
    return compact


def _compact_debt_run(
    index: int,
    run: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    text_limit: int,
) -> dict[str, Any]:
    tool_results = [
        _compact_debt_tool_result(tool_index, event)
        for tool_index, event in enumerate(event for event in events if event.get("event_type") == "tool.result")
    ]
    return {
        "index": index,
        "run_id": run.get("id"),
        "mission_id": run.get("mission_id"),
        "created_at": run.get("created_at"),
        "user_message": _clip(str(run.get("input_text") or ""), text_limit),
        "assistant_response": _clip(str(run.get("output_text") or ""), text_limit),
        "tool_results": tool_results[:12],
        "signals": {
            "tool_result_count": len(tool_results),
            "tool_names": sorted({str(item.get("tool") or "") for item in tool_results if item.get("tool")}),
        },
    }


def _compact_debt_tool_result(index: int, event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    item: dict[str, Any] = {
        "index": index,
        "tool": payload.get("tool_name"),
        "ok": bool(payload.get("ok")),
        "summary": _clip(str(payload.get("summary") or ""), 240),
    }
    if payload.get("error"):
        item["error"] = _clip(str(payload.get("error")), 160)
    evidence = payload.get("evidence")
    if isinstance(evidence, list) and evidence:
        item["evidence_kinds"] = sorted(
            {
                str(entry.get("kind"))
                for entry in evidence
                if isinstance(entry, dict) and entry.get("kind")
            }
        )
    return item


def _run_has_learning_candidate(events: list[dict[str, Any]]) -> bool:
    for event in events:
        if event.get("event_type") != "tool.result":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if str(payload.get("tool_name") or "") in LEARNING_CANDIDATE_TOOLS:
            return True
    return False


def _run_has_learning_debt_review(events: list[dict[str, Any]]) -> bool:
    for event in events:
        event_type = event.get("event_type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "learning.debt_review.completed":
            return True
        if event_type == "learning.reflection.started" and payload.get("packet_kind") == "learning_debt_packet":
            return True
    return False


def _clip(value: str, limit: int) -> str:
    compact = "\n".join(line.rstrip() for line in value.strip().splitlines())
    if len(compact) <= limit:
        return compact
    head = max(0, limit - 80)
    return compact[:head].rstrip() + "\n...[truncated]...\n" + compact[-60:].lstrip()


def _tool_result_has_learning_signal(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    tool_name = str(item.get("tool") or item.get("name") or "")
    return tool_name in LEARNING_CANDIDATE_TOOLS


def _is_main_turn_tool_result(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    tool_name = str(item.get("tool") or item.get("name") or "")
    return bool(tool_name) and tool_name != "learning_discard"
