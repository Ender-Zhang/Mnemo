from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core.ids import new_id
from ..core.jsonutil import dumps
from ..core.models import ToolCallEnvelope, ToolExecutionPolicy, ToolResult
from ..core.workspace import resolve_workspace_root
from ..memory import MemoryEngine
from ..providers import ProviderAdapter, ProviderRunInput, provider_capabilities_for_adapter
from ..storage import StateStore
from ..tools import ToolHarness, ToolRegistry, compact_tool_result
from .ledger import RunLedger


DREAM_SYSTEM_PROMPT = """You are Mnemo DreamCycle, a low-priority memory maintenance agent.
You do not answer the user. Review only the compact Dream delta and choose 0..N tool calls.
Stable memory changes must be explicit tool choices; do not assume facts not visible in the delta.
Use memory_promote_candidate only for draft candidates that are durable, personal, and useful.
Use memory_reject_candidate for low-value or non-personal draft candidates.
Use memory_tombstone for obsolete or harmful existing memories.
Use memory_decay_stale_pages only when health signals show expiry or decay is due.
Prefer doing nothing over maintaining low-signal items. Stay within the provided budget."""

DREAM_TOOL_NAMES = (
    "memory_search",
    "memory_read",
    "memory_health_report",
    "memory_decay_stale_pages",
    "memory_tombstone",
    "memory_promote_candidate",
    "memory_reject_candidate",
    "memory_write_candidate",
    "skill_propose_candidate",
    "tool_propose_candidate",
    "eval_propose_case",
    "learning_discard",
)


def run_dream_with_provider(
    *,
    state_dir: str | Path,
    provider: ProviderAdapter,
    workspace_root: str | Path | None = None,
    limit: int = 20,
    since: float | None = None,
    max_tool_rounds: int = 3,
    persist: bool = True,
) -> dict[str, Any]:
    store = StateStore(state_dir)
    store.initialize()
    engine = MemoryEngine(store)
    ledger = RunLedger(store)
    started_at = time.time()
    if since is None:
        since = _report_completed_at(engine.load_latest_dream_report())
    delta = engine.collect_dream_delta(limit=limit, since=since)
    plan = engine.build_dream_plan(delta, limit=limit)

    conversation_id = store.create_conversation("DreamCycle")
    mission_id = store.create_mission(conversation_id, "Dream memory maintenance")
    run_id = store.create_run(conversation_id, mission_id, "Dream memory maintenance")
    ledger.append(run_id, "dream.started", {"limit": limit, "since": since, "provider": provider.name})
    ledger.append(run_id, "dream.delta_collected", {"delta": delta})
    ledger.append(run_id, "dream.plan_recorded", {"plan": plan})

    registry = ToolRegistry.from_store(store)
    capabilities = provider_capabilities_for_adapter(provider)
    bundle = registry.tool_bundle(
        profile="full.v1",
        selected_tool_names=DREAM_TOOL_NAMES,
        provider_adapter_version=capabilities.adapter_version,
        cache_bust_reason="dream_maintenance",
    )
    harness = ToolHarness(
        store=store,
        ledger=ledger,
        registry=registry,
        policy=ToolExecutionPolicy(allowed_tools=bundle.tool_names),
        workspace_root=resolve_workspace_root(workspace_root, store.state_dir),
    )
    cache_plan = capabilities.cache_plan(bundle.metadata())
    ledger.append(
        run_id,
        "dream.model_request.prepared",
        {
            "tool_bundle": bundle.metadata(),
            "provider_capabilities": capabilities.metadata(),
            "cache_plan": cache_plan,
        },
    )

    messages = _dream_messages(delta, plan)
    tool_results: list[ToolResult] = []
    model_rounds: list[dict[str, Any]] = []
    model_text_parts: list[str] = []
    remaining_tool_calls = max(1, int(limit))

    for tool_round in range(max(1, int(max_tool_rounds))):
        tool_calls: list[ToolCallEnvelope] = []
        assistant_parts: list[str] = []
        completed_metadata: list[dict[str, Any]] = []
        for event in provider.stream(
            ProviderRunInput(
                messages=messages,
                tools=bundle.specs if remaining_tool_calls > 0 else (),
                metadata={
                    "run_id": run_id,
                    "stage": "dream_maintenance",
                    "tool_round": tool_round,
                    "tool_bundle": bundle.metadata(),
                    "provider_capabilities": capabilities.metadata(),
                    "cache_plan": cache_plan,
                },
            )
        ):
            if event.type == "text_delta" and event.text:
                assistant_parts.append(event.text)
                model_text_parts.append(event.text)
            elif event.type == "tool_call" and event.tool_call:
                tool_calls.append(event.tool_call)
            elif event.type == "completed":
                completed_metadata.append(event.metadata)

        assistant_text = "".join(assistant_parts)
        if remaining_tool_calls <= 0:
            tool_calls = []
        if len(tool_calls) > remaining_tool_calls:
            skipped_count = len(tool_calls) - remaining_tool_calls
            ledger.append(
                run_id,
                "dream.tool_budget_exhausted",
                {"tool_round": tool_round, "skipped_tool_calls": skipped_count},
            )
            tool_calls = tool_calls[:remaining_tool_calls]

        model_rounds.append(
            {
                "tool_round": tool_round,
                "tool_call_count": len(tool_calls),
                "metadata": completed_metadata,
                "assistant_text_preview": assistant_text[:300],
            }
        )
        ledger.append(run_id, "dream.model_completed", model_rounds[-1])
        if not tool_calls:
            break

        messages.append(_assistant_tool_call_message(tool_calls, assistant_text))
        for call in tool_calls:
            result = harness.execute(call, run_id=run_id, mission_id=mission_id)
            tool_results.append(result)
            remaining_tool_calls -= 1
            messages.append(_tool_result_message(result))
            if remaining_tool_calls <= 0:
                break

    snapshot = engine.compile_l1_snapshot(limit=50)
    completed_at = time.time()
    report = {
        "kind": "dream_report",
        "id": new_id("dream"),
        "started_at": started_at,
        "completed_at": completed_at,
        "since": since,
        "duration_s": round(completed_at - started_at, 3),
        "run_id": run_id,
        "delta": delta,
        "plan": plan,
        "execution": {
            "mode": "model_tool_calls",
            "result": {
                "tool_results": [_compact_dream_tool_result(result) for result in tool_results],
                "counts": {
                    "tool_calls": len(tool_results),
                    "succeeded": sum(1 for result in tool_results if result.ok),
                    "failed": sum(1 for result in tool_results if not result.ok),
                },
                "model_rounds": model_rounds,
                "model_text_preview": "".join(model_text_parts).strip()[:500],
                "snapshot": snapshot,
            },
        },
        "health_after": engine.health_report(limit=min(10, max(1, int(limit)))),
    }
    if persist:
        engine.save_dream_report(report)
    store.complete_run(run_id, _dream_run_summary(report))
    ledger.append(run_id, "dream.completed", {"report_id": report["id"], "execution": report["execution"]})
    ledger.append(run_id, "run.completed", {"status": "completed"})
    return report


def _dream_messages(delta: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": DREAM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "<dream_delta>\n"
                + dumps(delta)
                + "\n</dream_delta>\n<dream_plan>\n"
                + dumps(plan)
                + "\n</dream_plan>"
            ),
        },
    ]


def _assistant_tool_call_message(tool_calls: list[ToolCallEnvelope], content: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": dumps(call.arguments),
                },
            }
            for call in tool_calls
        ],
    }


def _tool_result_message(result: ToolResult) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": result.call_id,
        "content": dumps(compact_tool_result(result)),
    }


def _compact_dream_tool_result(result: ToolResult) -> dict[str, Any]:
    item: dict[str, Any] = {
        "call_id": result.call_id,
        "name": result.name,
        "ok": result.ok,
        "summary": result.summary,
    }
    if result.error:
        item["error"] = result.error[:200]
    evidence = result.evidence if isinstance(result.evidence, list) else []
    if evidence:
        item["evidence"] = evidence[:5]
    if result.name == "memory_promote_candidate":
        item["decision"] = result.result.get("decision")
        item["candidate_id"] = result.result.get("candidate_id")
        item["page_id"] = result.result.get("page_id")
        item["status"] = result.result.get("status")
    elif result.name == "memory_reject_candidate":
        item["candidate_id"] = result.result.get("candidate_id")
        item["status"] = result.result.get("status")
        item["tombstone_id"] = result.result.get("tombstone_id")
    elif result.name == "memory_tombstone":
        item["memory_id"] = result.result.get("memory_id")
        item["target_type"] = result.result.get("target_type")
        item["status"] = result.result.get("status")
        item["tombstone_id"] = result.result.get("tombstone_id")
    elif result.name == "memory_decay_stale_pages":
        item["counts"] = result.result.get("counts", {})
    elif result.name == "memory_write_candidate":
        item["candidate_id"] = result.result.get("candidate_id")
        item["status"] = result.result.get("status")
    return item


def _dream_run_summary(report: dict[str, Any]) -> str:
    execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    return f"Dream maintenance completed with {counts.get('tool_calls', 0)} model-selected tool calls."


def _report_completed_at(report: dict[str, Any] | None) -> float | None:
    if not report:
        return None
    try:
        completed_at = float(report.get("completed_at") or 0.0)
    except (TypeError, ValueError):
        return None
    return completed_at or None
