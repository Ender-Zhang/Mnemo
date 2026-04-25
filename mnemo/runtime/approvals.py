from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import ToolError
from ..core.models import ToolCallEnvelope, ToolExecutionPolicy, ToolResult
from ..storage import StateStore
from ..tools import ToolHarness, ToolRegistry, compact_tool_result
from .ledger import RunLedger


APPROVED_TOOL_CALL_SUFFIX = "approved"


def resolve_inbox_item_with_actions(
    store: StateStore,
    item_id: str,
    resolution: str,
    *,
    notes: str | None = None,
    workspace_root: str | Path | None = None,
    source: str = "runtime",
) -> dict[str, Any]:
    before = store.get_inbox_item(item_id)
    if not before:
        raise ValueError(f"inbox item not found: {item_id}")
    approval_call = _approval_call_from_item(store, before) if _should_execute_tool_approval(before, resolution) else None
    item = store.resolve_inbox_item(item_id, resolution, notes=notes)
    result: dict[str, Any] = {"item": item}

    if item.get("source_run_id"):
        store.append_event(
            item["source_run_id"],
            "inbox.resolved",
            {
                "item_id": item["id"],
                "resolution": item.get("resolution"),
                "changed": item.get("changed"),
                "source": source,
            },
        )

    if approval_call and item.get("changed"):
        tool_result = _execute_approved_tool_call(
            store,
            item=before,
            call=approval_call,
            workspace_root=workspace_root,
            source=source,
        )
        result["tool_result"] = _approval_tool_result_payload(tool_result)
    return result


def _should_execute_tool_approval(item: dict[str, Any], resolution: str) -> bool:
    return (
        item.get("status") == "open"
        and item.get("action_type") == "tool_approval"
        and str(resolution or "").strip() == "accepted"
    )


def _approval_call_from_item(store: StateStore, item: dict[str, Any]) -> ToolCallEnvelope:
    action_data = item.get("action_data") or {}
    tool_call = action_data.get("tool_call") if isinstance(action_data, dict) else None
    if not isinstance(tool_call, dict):
        raise ValueError("tool approval action_data.tool_call is required")
    source_run_id = item.get("source_run_id")
    if not source_run_id:
        raise ValueError("tool approval source_run_id is required")
    run = store.get_run(str(source_run_id))
    if not run:
        raise ValueError(f"tool approval source run not found: {source_run_id}")

    name = _required_str(tool_call, "tool_name")
    _validate_tool_exists(store, name)
    arguments = tool_call.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError("tool approval arguments must be an object")
    original_call_id = _optional_str(tool_call.get("call_id")) or item["id"]
    return ToolCallEnvelope(
        call_id=f"{original_call_id}:{APPROVED_TOOL_CALL_SUFFIX}:{item['id']}",
        name=name,
        arguments=arguments,
        provider=_optional_str(tool_call.get("provider")) or "approval",
        risk=_optional_str(tool_call.get("risk")) or "admin",
        source="user_approved",
    )


def _validate_tool_exists(store: StateStore, name: str) -> None:
    try:
        ToolRegistry.from_store(store).spec(name)
    except ToolError as exc:
        raise ValueError(str(exc)) from exc


def _execute_approved_tool_call(
    store: StateStore,
    *,
    item: dict[str, Any],
    call: ToolCallEnvelope,
    workspace_root: str | Path | None,
    source: str,
) -> ToolResult:
    run_id = str(item["source_run_id"])
    run = store.get_run(run_id)
    if not run:
        raise ValueError(f"tool approval source run not found: {run_id}")
    mission_id = str(run["mission_id"])
    ledger = RunLedger(store)
    registry = ToolRegistry.from_store(store)
    spec = registry.spec(call.name)
    ledger.append(
        run_id,
        "tool.approval.executing",
        {
            "item_id": item["id"],
            "tool_name": call.name,
            "risk": spec.risk,
            "source": source,
        },
    )
    result = ToolHarness(
        store=store,
        ledger=ledger,
        registry=registry,
        policy=ToolExecutionPolicy(
            allowed_risks=("read", "write", "external", "admin"),
            allowed_tools=(call.name,),
        ),
        workspace_root=workspace_root,
    ).execute(call, run_id=run_id, mission_id=mission_id)
    ledger.append(
        run_id,
        "tool.approval.executed",
        {
            "item_id": item["id"],
            "tool_name": result.name,
            "ok": result.ok,
            "summary": result.summary,
            "source": source,
        },
    )
    return result


def _approval_tool_result_payload(result: ToolResult) -> dict[str, Any]:
    compact = compact_tool_result(result)
    compact["call_id"] = result.call_id
    compact["name"] = result.name
    compact["ok"] = result.ok
    return compact


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"tool approval {key} is required")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
