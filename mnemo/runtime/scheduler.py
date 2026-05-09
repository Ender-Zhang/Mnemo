from __future__ import annotations

from datetime import datetime
import re
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

from ..memory import MemoryEngine
from ..storage import StateStore


WATCH_FEEDBACK_OUTCOMES = ("notified", "silent", "no_feedback", "useful", "not_useful", "dismissed")
WATCH_POLICY_ACTIONS = ("keep", "sparsify", "pause", "disable")
DEFAULT_DREAM_LIMIT = 20
DEFAULT_DREAM_MIN_CONFIDENCE = 0.7
DEFAULT_AUTO_DREAM_SCHEDULE = "daily"
DEFAULT_AUTO_DREAM_TITLE = "Automatic Dream maintenance"
AUTO_DREAM_SOURCE = "service"


class ScheduleService:
    """Lightweight scheduled-item service for queue work and bounded Dream maintenance."""

    def __init__(self, state_dir: str | Path) -> None:
        self.store = StateStore(state_dir)

    def add_watch(
        self,
        *,
        target: str,
        instruction: str,
        schedule: str = "daily",
        source: str = "cli",
        next_run_at: float | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.store.initialize()
        clean_target = _require_text(target, "watch target")
        clean_instruction = _require_text(instruction, "watch instruction")
        due_at = _initial_due_time(schedule, next_run_at=next_run_at)
        item_id = self.store.add_scheduled_item(
            kind="watch",
            title=clean_target,
            instruction=clean_instruction,
            schedule=schedule,
            source=source,
            next_run_at=due_at,
            metadata=metadata or {},
        )
        return self.store.get_scheduled_item(item_id) or {}

    def add_cron(
        self,
        *,
        message: str,
        schedule: str,
        title: str | None = None,
        source: str = "cli",
        next_run_at: float | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.store.initialize()
        clean_message = _require_text(message, "cron message")
        clean_schedule = _require_text(schedule, "cron schedule")
        due_at = _initial_due_time(clean_schedule, next_run_at=next_run_at)
        item_id = self.store.add_scheduled_item(
            kind="cron",
            title=title.strip() if isinstance(title, str) and title.strip() else _preview(clean_message),
            instruction=clean_message,
            schedule=clean_schedule,
            source=source,
            next_run_at=due_at,
            metadata=metadata or {},
        )
        return self.store.get_scheduled_item(item_id) or {}

    def add_dream(
        self,
        *,
        schedule: str = "daily",
        title: str | None = None,
        source: str = "cli",
        next_run_at: float | str | None = None,
        limit: int = DEFAULT_DREAM_LIMIT,
        min_confidence: float = DEFAULT_DREAM_MIN_CONFIDENCE,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.store.initialize()
        clean_schedule = _require_text(schedule, "dream schedule")
        dream_metadata = dict(metadata or {})
        dream_metadata["dream"] = {
            "limit": _bounded_dream_limit(limit),
            "min_confidence": _bounded_dream_confidence(min_confidence),
        }
        due_at = _initial_due_time(clean_schedule, next_run_at=next_run_at)
        item_id = self.store.add_scheduled_item(
            kind="dream",
            title=title.strip() if isinstance(title, str) and title.strip() else "Dream maintenance",
            instruction="Run Dream memory maintenance",
            schedule=clean_schedule,
            source=source,
            next_run_at=due_at,
            metadata=dream_metadata,
        )
        return self.store.get_scheduled_item(item_id) or {}

    def list_items(
        self,
        *,
        kind: str | None = None,
        status: str | None = "active",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.store.initialize()
        return self.store.list_scheduled_items(kind=kind, status=status, limit=limit)

    def update_status(self, item_id: str, status: str) -> dict[str, Any]:
        self.store.initialize()
        return self.store.update_scheduled_item_status(item_id, status)

    def record_watch_feedback(
        self,
        item_id: str,
        *,
        outcome: str,
        note: str = "",
        decision: dict[str, Any] | None = None,
        now: float | str | None = None,
    ) -> dict[str, Any]:
        self.store.initialize()
        feedback_at = parse_schedule_time(now) if now is not None else time.time()
        item = self.store.get_scheduled_item(item_id)
        if not item:
            raise ValueError(f"scheduled item not found: {item_id}")
        if item["kind"] != "watch":
            raise ValueError(f"scheduled item is not a watch: {item_id}")

        clean_outcome = _normalize_watch_feedback_outcome(outcome)
        clean_decision = _normalize_watch_policy_decision(decision)
        metadata = dict(item.get("metadata") or {})
        feedback = _updated_watch_feedback_metadata(
            metadata.get("watch_feedback"),
            outcome=clean_outcome,
            note=note,
            decision=clean_decision,
            now=feedback_at,
        )
        metadata["watch_feedback"] = feedback
        schedule, status, next_run_at = _watch_policy_update(item, clean_decision, now=feedback_at)
        updated = self.store.update_scheduled_item_policy(
            item_id,
            schedule=schedule,
            status=status,
            next_run_at=next_run_at,
            update_next_run_at=schedule is not None or status in {"paused", "disabled"},
            metadata=metadata,
        )
        return {
            "kind": "watch_feedback",
            "version": "mnemo.watch_feedback.v1",
            "item": updated,
            "feedback": feedback,
            "decision": clean_decision,
        }

    def tick(
        self,
        *,
        now: float | str | None = None,
        limit: int = 50,
        kind: str | None = None,
        dream_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.store.initialize()
        tick_at = parse_schedule_time(now) if now is not None else time.time()
        clean_kind = _normalize_tick_kind(kind) if kind is not None else None
        fetch_limit = max(int(limit), 1000) if clean_kind else int(limit)
        due_items = self.store.due_scheduled_items(now=tick_at, limit=fetch_limit)
        if clean_kind:
            due_items = [item for item in due_items if item.get("kind") == clean_kind][: max(0, int(limit))]
        processed: list[dict[str, Any]] = []
        for item in due_items:
            processed.append(self._enqueue_due_item(item, now=tick_at, dream_runner=dream_runner))
        return {
            "processed": processed,
            "queue": self.store.queue_stats(),
            "scheduled": scheduled_item_stats(self.store),
        }

    def _enqueue_due_item(
        self,
        item: dict[str, Any],
        *,
        now: float,
        dream_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if item.get("kind") == "dream":
            return self._run_due_dream(item, now=now, dream_runner=dream_runner)

        item_id = str(item["id"])
        try:
            queue_id = self.store.enqueue_run_request(
                _run_message(item),
                metadata={
                    "source": "scheduler",
                    "scheduled_item_id": item_id,
                    "scheduled_kind": item["kind"],
                    "schedule": item["schedule"],
                    "title": item["title"],
                },
                available_at=now,
            )
            next_due = next_due_time(str(item["schedule"]), after=now)
            status = "active" if next_due is not None else "completed"
            updated = self.store.record_scheduled_item_tick(
                item_id,
                next_run_at=next_due,
                queue_id=queue_id,
                status=status,
                now=now,
            )
            return {
                "scheduled_item_id": item_id,
                "queue_id": queue_id,
                "status": "queued",
                "item_status": updated["status"],
                "next_run_at": updated["next_run_at"],
            }
        except Exception as exc:
            self.store.record_scheduled_item_tick(
                item_id,
                next_run_at=item.get("next_run_at"),
                error=str(exc),
                now=now,
            )
            return {"scheduled_item_id": item_id, "status": "failed", "error": str(exc)}

    def _run_due_dream(
        self,
        item: dict[str, Any],
        *,
        now: float,
        dream_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        item_id = str(item["id"])
        try:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            dream_config = metadata.get("dream") if isinstance(metadata.get("dream"), dict) else {}
            limit = _bounded_dream_limit(dream_config.get("limit", DEFAULT_DREAM_LIMIT))
            min_confidence = _bounded_dream_confidence(
                dream_config.get("min_confidence", DEFAULT_DREAM_MIN_CONFIDENCE)
            )
            report = (
                dream_runner(item)
                if dream_runner is not None
                else MemoryEngine(self.store).dream_maintenance(limit=limit, min_confidence=min_confidence)
            )
            next_due = next_due_time(str(item["schedule"]), after=now)
            status = "active" if next_due is not None else "completed"
            updated = self.store.record_scheduled_item_tick(
                item_id,
                next_run_at=next_due,
                status=status,
                now=now,
            )
            updated_metadata = dict(updated.get("metadata") or {})
            updated_metadata["last_dream_report"] = _compact_dream_tick_report(report)
            updated = self.store.update_scheduled_item_policy(item_id, metadata=updated_metadata)
            return {
                "scheduled_item_id": item_id,
                "status": "dream_completed",
                "item_status": updated["status"],
                "next_run_at": updated["next_run_at"],
                "dream_report": updated_metadata["last_dream_report"],
            }
        except Exception as exc:
            self.store.record_scheduled_item_tick(
                item_id,
                next_run_at=item.get("next_run_at"),
                error=str(exc),
                now=now,
            )
            return {"scheduled_item_id": item_id, "status": "failed", "error": str(exc)}


def ensure_default_dream_schedule(
    state_dir: str | Path,
    *,
    now: float | str | None = None,
    schedule: str = DEFAULT_AUTO_DREAM_SCHEDULE,
    limit: int = DEFAULT_DREAM_LIMIT,
    min_confidence: float = DEFAULT_DREAM_MIN_CONFIDENCE,
) -> dict[str, Any]:
    service = ScheduleService(state_dir)
    existing = _existing_default_dream_schedule(service)
    if existing:
        return {"created": False, "item": existing}

    item = service.add_dream(
        title=DEFAULT_AUTO_DREAM_TITLE,
        schedule=schedule,
        source=AUTO_DREAM_SOURCE,
        next_run_at=parse_schedule_time(now) if now is not None else time.time(),
        limit=limit,
        min_confidence=min_confidence,
        metadata={"auto_dream": True},
    )
    return {"created": True, "item": item}


def scheduled_item_stats(store: StateStore) -> dict[str, Any]:
    items = store.list_scheduled_items(status=None, limit=1000)
    counts: dict[str, dict[str, int]] = {}
    for item in items:
        kind = str(item.get("kind") or "unknown")
        status = str(item.get("status") or "unknown")
        counts.setdefault(kind, {})
        counts[kind][status] = counts[kind].get(status, 0) + 1
    due_count = len(store.due_scheduled_items(limit=1000))
    return {
        "total": len(items),
        "due": due_count,
        "counts": counts,
        "next": [_scheduled_card(item) for item in store.list_scheduled_items(status="active", limit=5)],
    }


def parse_schedule_time(value: float | int | str | None) -> float:
    if value is None:
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip()
    if not text:
        raise ValueError("schedule time is required")
    if text.casefold() == "now":
        return time.time()
    try:
        return float(text)
    except ValueError:
        pass
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid schedule time: {value}") from exc
    return parsed.timestamp()


def next_due_time(schedule: str, *, after: float | None = None) -> float | None:
    normalized = _normalize_schedule(schedule)
    base = time.time() if after is None else float(after)
    if normalized == "once" or normalized.startswith("at:"):
        return None
    return base + _schedule_interval_s(normalized)


def _initial_due_time(schedule: str, *, next_run_at: float | str | None = None) -> float:
    if next_run_at is not None:
        return parse_schedule_time(next_run_at)
    normalized = _normalize_schedule(schedule)
    now = time.time()
    if normalized == "once":
        return now
    if normalized.startswith("at:"):
        return parse_schedule_time(normalized.split(":", 1)[1])
    return now + _schedule_interval_s(normalized)


def _schedule_interval_s(schedule: str) -> float:
    if schedule == "hourly":
        return 60 * 60
    if schedule == "daily":
        return 24 * 60 * 60
    if schedule == "weekly":
        return 7 * 24 * 60 * 60
    every_colon = re.fullmatch(r"every:(\d+(?:\.\d+)?)", schedule)
    if every_colon:
        return _positive_interval(every_colon.group(1), schedule)
    every_unit = re.fullmatch(r"every\s+(\d+(?:\.\d+)?)\s*([smhdw])", schedule)
    if every_unit:
        magnitude = _positive_interval(every_unit.group(1), schedule)
        unit = every_unit.group(2)
        multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        return magnitude * multiplier
    raise ValueError(f"unsupported schedule: {schedule}")


def _positive_interval(raw: str, schedule: str) -> float:
    value = float(raw)
    if value <= 0:
        raise ValueError(f"schedule interval must be positive: {schedule}")
    return value


def _normalize_schedule(schedule: str) -> str:
    normalized = " ".join(str(schedule or "").strip().casefold().split())
    if not normalized:
        raise ValueError("schedule is required")
    if normalized.startswith("at:"):
        return f"at:{normalized.split(':', 1)[1].strip()}"
    return normalized


def _normalize_tick_kind(kind: str) -> str:
    normalized = str(kind or "").strip().casefold()
    if normalized not in {"watch", "cron", "dream"}:
        raise ValueError(f"invalid scheduled item kind: {kind}")
    return normalized


def _existing_default_dream_schedule(service: ScheduleService) -> dict[str, Any] | None:
    items = service.list_items(kind="dream", status=None, limit=1000)
    for item in items:
        if item.get("status") == "active":
            return item
    for item in items:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if metadata.get("auto_dream"):
            return item
    return None


def _normalize_watch_feedback_outcome(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in WATCH_FEEDBACK_OUTCOMES:
        known = ", ".join(WATCH_FEEDBACK_OUTCOMES)
        raise ValueError(f"invalid watch feedback outcome: {value}. Known outcomes: {known}")
    return normalized


def _normalize_watch_policy_decision(decision: dict[str, Any] | None) -> dict[str, Any]:
    if not decision:
        return {"action": "keep", "source": "none"}
    action = str(decision.get("action") or "keep").strip().casefold()
    if action not in WATCH_POLICY_ACTIONS:
        known = ", ".join(WATCH_POLICY_ACTIONS)
        raise ValueError(f"invalid watch policy action: {action}. Known actions: {known}")
    result = {
        "action": action,
        "source": str(decision.get("source") or "model").strip() or "model",
    }
    reason = str(decision.get("reason") or "").strip()
    if reason:
        result["reason"] = _preview(reason, limit=240)
    schedule = str(decision.get("schedule") or "").strip()
    if schedule:
        result["schedule"] = _normalize_schedule(schedule)
        if next_due_time(result["schedule"], after=0) is None:
            raise ValueError("watch policy schedule must be recurring")
    if action == "sparsify" and "schedule" not in result:
        raise ValueError("watch policy action sparsify requires schedule")
    return result


def _updated_watch_feedback_metadata(
    existing: Any,
    *,
    outcome: str,
    note: str,
    decision: dict[str, Any],
    now: float,
) -> dict[str, Any]:
    feedback = existing if isinstance(existing, dict) else {}
    counts = feedback.get("counts") if isinstance(feedback.get("counts"), dict) else {}
    streaks = feedback.get("streaks") if isinstance(feedback.get("streaks"), dict) else {}
    counts[outcome] = int(counts.get(outcome, 0)) + 1
    last_outcome = str(feedback.get("last_outcome") or "")
    if outcome == last_outcome:
        streaks[outcome] = int(streaks.get(outcome, 0)) + 1
    else:
        streaks = {outcome: 1}
    history = feedback.get("recent") if isinstance(feedback.get("recent"), list) else []
    history = [
        *history[-4:],
        {
            "outcome": outcome,
            "note": _preview(note, limit=160) if note else "",
            "decision_action": decision["action"],
            "at": now,
        },
    ]
    return {
        "counts": counts,
        "streaks": streaks,
        "last_outcome": outcome,
        "last_decision": decision,
        "recent": history,
        "updated_at": now,
    }


def _watch_policy_update(
    item: dict[str, Any],
    decision: dict[str, Any],
    *,
    now: float,
) -> tuple[str | None, str | None, float | None]:
    action = decision["action"]
    if action == "keep":
        schedule = decision.get("schedule")
        return schedule, None, next_due_time(schedule, after=now) if schedule else None
    if action == "sparsify":
        schedule = str(decision["schedule"])
        return schedule, "active", next_due_time(schedule, after=now)
    if action == "pause":
        return None, "paused", None
    if action == "disable":
        return None, "disabled", None
    return None, None, None


def _run_message(item: dict[str, Any]) -> str:
    if item.get("kind") == "watch":
        return (
            f"Watch check: {item.get('title')}\n"
            f"Instruction: {item.get('instruction')}\n"
            "Decide whether the user should be notified, whether an Inbox item is needed, "
            "or whether this should stay silent."
        )
    return str(item.get("instruction") or "")


def _compact_dream_tick_report(report: dict[str, Any]) -> dict[str, Any]:
    execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    actions = result.get("actions") if isinstance(result.get("actions"), dict) else {}
    action_counts = actions.get("counts") if isinstance(actions.get("counts"), dict) else {}
    return {
        "id": report.get("id"),
        "completed_at": report.get("completed_at"),
        "mode": execution.get("mode"),
        "promoted": len(result.get("promoted", [])),
        "rejected": len(result.get("rejected", [])),
        "skipped": len(result.get("skipped", [])),
        "conflicts": len(result.get("conflicts", [])),
        "tool_calls": counts.get("tool_calls", 0),
        "actions_applied": action_counts.get("applied", 0),
        "actions_skipped": action_counts.get("skipped", 0),
        "snapshot_items": snapshot.get("page_count", 0),
    }


def _scheduled_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "title": item.get("title"),
        "status": item.get("status"),
        "schedule": item.get("schedule"),
        "next_run_at": item.get("next_run_at"),
        "last_run_at": item.get("last_run_at"),
    }


def _require_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _bounded_dream_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_DREAM_LIMIT
    return min(200, max(1, parsed))


def _bounded_dream_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_DREAM_MIN_CONFIDENCE
    return min(1.0, max(0.0, parsed))


def _preview(value: str, limit: int = 80) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."
