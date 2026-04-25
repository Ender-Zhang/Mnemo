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
        if item.get("tool")
        in {"memory_write_candidate", "skill_propose_candidate", "tool_propose_candidate", "eval_propose_case"}
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


def _compact_tool_result(index: int, result: ToolResult) -> dict[str, Any]:
    compact = compact_tool_result(result)
    compact["index"] = index
    compact["call_id"] = result.call_id
    return compact


def _clip(value: str, limit: int) -> str:
    compact = "\n".join(line.rstrip() for line in value.strip().splitlines())
    if len(compact) <= limit:
        return compact
    head = max(0, limit - 80)
    return compact[:head].rstrip() + "\n...[truncated]...\n" + compact[-60:].lstrip()
