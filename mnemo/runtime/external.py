from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
from typing import Any, Sequence

from ..core.errors import MnemoError
from ..core.jsonutil import dumps
from ..core.models import RunRequest
from ..storage import StateStore
from .capsule import ContextCapsuleBuilder
from .ledger import RunLedger
from .state import resolve_conversation, resolve_mission


EXTERNAL_RUNTIME_VERSION = "mnemo.external_runtime.v1"
DEFAULT_EXTERNAL_TIMEOUT_S = 30.0
DEFAULT_STDIO_BYTE_LIMIT = 128_000
_PROPOSAL_FIELDS = {
    "summary",
    "evidence",
    "files_changed",
    "artifact_patches",
    "memory_observations",
    "skill_patches",
    "open_questions",
    "confidence",
}


class ExternalRuntimeError(MnemoError):
    """Raised when an external runtime adapter cannot complete safely."""


@dataclass(frozen=True)
class ExternalRunRequest:
    task: str
    state_dir: str | Path
    command: Sequence[str]
    runtime: str = "external-command"
    agent_type: str = "general"
    requested_pages: Sequence[str] | None = None
    allowed_pages: Sequence[str] | None = None
    conversation_id: str | None = None
    mission_id: str | None = None
    workspace_root: str | Path | None = None
    timeout_s: float = DEFAULT_EXTERNAL_TIMEOUT_S


def run_external(request: ExternalRunRequest) -> dict[str, Any]:
    """Run an explicit argv command as a proposal-only external runtime."""

    task = _required_text(request.task, "task")
    command = _normalize_command(request.command)
    timeout_s = _normalize_timeout(request.timeout_s)
    workspace_root = _normalize_workspace_root(request.workspace_root)

    store = StateStore(request.state_dir)
    store.initialize()
    ledger = RunLedger(store)
    run_request = RunRequest(
        message=task,
        state_dir=str(request.state_dir),
        conversation_id=request.conversation_id,
        mission_id=request.mission_id,
        workspace_root=str(workspace_root) if workspace_root else None,
        prompt_mode="capsule",
    )
    conversation_id = resolve_conversation(store, run_request, title=_compact_text(task, limit=80))
    mission_id = resolve_mission(store, conversation_id, run_request, brief=_compact_text(task, limit=120))
    run_id = store.create_run(conversation_id, mission_id, task)

    ledger.append(
        run_id,
        "request.received",
        {
            "conversation_id": conversation_id,
            "mission_id": mission_id,
            "message": task,
            "source": "external_runtime",
            "runtime": _compact_text(request.runtime, limit=64) or "external-command",
        },
    )

    capsule = ContextCapsuleBuilder(store).build(
        task,
        runtime=request.runtime,
        agent_type=request.agent_type,
        requested_pages=list(request.requested_pages or ()),
        allowed_pages=list(request.allowed_pages or ()),
        conversation_id=conversation_id,
        mission_id=mission_id,
    )
    ledger.append(
        run_id,
        "external.capsule.prepared",
        {
            "capsule_id": capsule["capsule_id"],
            "runtime": capsule["runtime"],
            "agent_type": capsule["agent_type"],
            "requested_page_count": len(capsule.get("requested_pages", {}).get("ids", [])),
            "allowed_page_count": len(capsule.get("allowed_pages", [])),
            "blocked_page_count": len(capsule.get("requested_pages", {}).get("blocked", [])),
            "unresolved_page_count": len(capsule.get("requested_pages", {}).get("unresolved", [])),
        },
    )

    envelope = {
        "kind": "runtime_adapter_request",
        "version": EXTERNAL_RUNTIME_VERSION,
        "runtime": capsule["runtime"],
        "agent_type": capsule["agent_type"],
        "task": task,
        "capsule": capsule,
        "return_contract": capsule["return_contract"],
        "response_format": {
            "type": "json_object",
            "side_effects": "proposals_only",
            "allowed_fields": sorted(_PROPOSAL_FIELDS),
        },
    }

    ledger.append(
        run_id,
        "external.runtime.started",
        {
            "runtime": capsule["runtime"],
            "command": _command_preview(command),
            "timeout_s": timeout_s,
            "cwd": str(workspace_root) if workspace_root else None,
        },
    )

    try:
        completed = subprocess.run(
            list(command),
            input=dumps(envelope),
            text=True,
            capture_output=True,
            cwd=workspace_root,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _fail_run(
            store,
            ledger,
            run_id,
            "external.runtime.failed",
            {
                "reason": "timeout",
                "timeout_s": timeout_s,
                "stdout_bytes": _byte_count(exc.stdout),
                "stderr_bytes": _byte_count(exc.stderr),
            },
        )
        raise ExternalRuntimeError(f"external runtime timed out after {timeout_s:g}s") from exc
    except OSError as exc:
        _fail_run(
            store,
            ledger,
            run_id,
            "external.runtime.failed",
            {"reason": "process_error", "error": _compact_text(exc, limit=240)},
        )
        raise ExternalRuntimeError(f"external runtime failed to start: {exc}") from exc

    raw_stdout = completed.stdout or ""
    raw_stderr = completed.stderr or ""
    stdout_bytes = len(raw_stdout.encode("utf-8"))
    stderr_bytes = len(raw_stderr.encode("utf-8"))
    stdout = _truncate_bytes(raw_stdout, DEFAULT_STDIO_BYTE_LIMIT)
    stderr = _truncate_bytes(raw_stderr, DEFAULT_STDIO_BYTE_LIMIT)
    ledger.append(
        run_id,
        "external.runtime.completed",
        {
            "exit_code": completed.returncode,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "stdout_truncated": stdout_bytes > DEFAULT_STDIO_BYTE_LIMIT,
            "stderr_truncated": stderr_bytes > DEFAULT_STDIO_BYTE_LIMIT,
        },
    )
    if completed.returncode != 0:
        _fail_run(
            store,
            ledger,
            run_id,
            "external.runtime.failed",
            {
                "reason": "nonzero_exit",
                "exit_code": completed.returncode,
                "stderr_preview": _compact_text(stderr, limit=240),
            },
        )
        raise ExternalRuntimeError(f"external runtime exited with code {completed.returncode}")

    parsed = _parse_external_output(stdout)
    proposal, ignored_fields = _sanitize_proposal(parsed, stdout)

    if ignored_fields:
        ledger.append(
            run_id,
            "runtime.boundary_violation",
            {
                "ignored_fields": ignored_fields,
                "reason": "external_runtime_returned_non_proposal_fields",
            },
        )
    ledger.append(run_id, "external.result.proposed", proposal)
    if proposal["artifact_patches"]:
        ledger.append(run_id, "artifact.patch.proposed", {"items": proposal["artifact_patches"]})
    if proposal["memory_observations"]:
        ledger.append(run_id, "memory.observation.proposed", {"items": proposal["memory_observations"]})
    if proposal["skill_patches"]:
        ledger.append(run_id, "skill.patch.proposed", {"items": proposal["skill_patches"]})

    _update_external_checkpoint(store, mission_id, run_id, request.runtime, proposal["summary"])
    store.complete_run(run_id, proposal["summary"], status="completed")
    ledger.append(run_id, "run.completed", {"status": "completed"})

    return {
        "kind": "external_runtime_result",
        "version": EXTERNAL_RUNTIME_VERSION,
        "run_id": run_id,
        "conversation_id": conversation_id,
        "mission_id": mission_id,
        "runtime": capsule["runtime"],
        "agent_type": capsule["agent_type"],
        "capsule": _capsule_summary(capsule),
        "proposal": proposal,
        "ignored_fields": ignored_fields,
        "exit_code": completed.returncode,
    }


def _fail_run(
    store: StateStore,
    ledger: RunLedger,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    ledger.append(run_id, event_type, payload)
    ledger.append(run_id, "run.completed", {"status": "failed", **payload})
    store.complete_run(run_id, f"External runtime failed: {payload.get('reason') or event_type}", status="failed")


def _parse_external_output(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    for candidate in (text, _last_nonempty_line(text)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        return {"summary": parsed}
    return {"summary": text}


def _sanitize_proposal(payload: dict[str, Any], stdout: str) -> tuple[dict[str, Any], list[str]]:
    ignored_fields = sorted(str(key) for key in payload if str(key) not in _PROPOSAL_FIELDS)
    summary = _compact_text(payload.get("summary") or stdout or "External runtime completed.", limit=2000)
    proposal = {
        "summary": summary or "External runtime completed.",
        "evidence": _compact_list(payload.get("evidence"), limit=20),
        "files_changed": _compact_list(payload.get("files_changed"), limit=20),
        "artifact_patches": _compact_list(payload.get("artifact_patches"), limit=10),
        "memory_observations": _compact_list(payload.get("memory_observations"), limit=10),
        "skill_patches": _compact_list(payload.get("skill_patches"), limit=10),
        "open_questions": _compact_list(payload.get("open_questions"), limit=10),
        "confidence": _confidence(payload.get("confidence")),
    }
    return proposal, ignored_fields


def _compact_list(value: Any, *, limit: int) -> list[Any]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [_compact_value(item, depth=0) for item in items[: max(0, int(limit))]]


def _compact_value(value: Any, *, depth: int) -> Any:
    if isinstance(value, str):
        return _compact_text(value, limit=500)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        if depth >= 2:
            return {"keys": sorted(str(key) for key in value)[:20]}
        compact: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 20:
                compact["..."] = "truncated"
                break
            compact[_compact_text(key, limit=80)] = _compact_value(item, depth=depth + 1)
        return compact
    if isinstance(value, list):
        if depth >= 2:
            return {"count": len(value)}
        return [_compact_value(item, depth=depth + 1) for item in value[:20]]
    return _compact_text(value, limit=240)


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, parsed))


def _capsule_summary(capsule: dict[str, Any]) -> dict[str, Any]:
    requested = capsule.get("requested_pages", {})
    return {
        "kind": capsule.get("kind"),
        "version": capsule.get("version"),
        "capsule_id": capsule.get("capsule_id"),
        "runtime": capsule.get("runtime"),
        "agent_type": capsule.get("agent_type"),
        "task": capsule.get("task"),
        "return_contract": capsule.get("return_contract"),
        "allowed_page_count": len(capsule.get("allowed_pages", [])),
        "blocked_page_count": len(requested.get("blocked", [])) if isinstance(requested, dict) else 0,
        "unresolved_page_count": len(requested.get("unresolved", [])) if isinstance(requested, dict) else 0,
    }


def _update_external_checkpoint(
    store: StateStore,
    mission_id: str,
    run_id: str,
    runtime: str,
    summary: str,
) -> None:
    mission = store.get_mission(mission_id) or {}
    checkpoint = mission.get("checkpoint") if isinstance(mission.get("checkpoint"), dict) else {}
    checkpoint = {
        **checkpoint,
        "last_run_id": run_id,
        "last_external_runtime": _compact_text(runtime, limit=64) or "external-command",
        "last_external_summary": _compact_text(summary, limit=240),
    }
    store.update_mission_checkpoint(mission_id, checkpoint)


def _normalize_command(command: Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, (str, bytes)):
        raise ValueError("command must be an argv array of strings")
    argv: list[str] = []
    for item in command:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("command must be an argv array of non-empty strings")
        argv.append(item)
    if not argv:
        raise ValueError("command is required")
    return tuple(argv)


def _normalize_timeout(value: float) -> float:
    try:
        timeout_s = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_s must be a number") from exc
    if timeout_s <= 0:
        raise ValueError("timeout_s must be greater than 0")
    return min(timeout_s, 3600.0)


def _normalize_workspace_root(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError(f"workspace_root is not a directory: {value}")
    return path


def _command_preview(command: Sequence[str]) -> list[str]:
    preview = [_compact_text(item, limit=120) for item in command[:8]]
    if len(command) > 8:
        preview.append("...")
    return preview


def _byte_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        return len(value)
    return len(str(value).encode("utf-8"))


def _truncate_bytes(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _required_text(value: Any, field: str) -> str:
    text = _compact_text(value, limit=1200)
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."
