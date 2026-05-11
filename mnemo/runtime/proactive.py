from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..channels.feishu import (
    FeishuChannelConfig,
    FeishuClient,
    feishu_proactive_targets,
    load_feishu_saved_config,
)
from ..core.models import RunRequest, RunResult
from ..core.settings import load_user_settings
from ..storage import StateStore
from .daemon import DaemonRunner
from .scheduler import ScheduleService


PROACTIVE_STATE_VERSION = "mnemo.proactive.v1"
PROACTIVE_WORKER_ID = f"proactive:{os.getpid()}"
_DELIVERY_RETRY_ATTEMPT_LIMIT = 5
_INTERNAL_WATCH_OUTPUT_PATTERNS = (
    "watch_feedback",
    "scheduled item",
    "scheduled_item",
    "watch check",
    "outcome=",
    "本轮 watch",
    "本轮watch",
    "飞书 channel",
    "feishu channel",
    "飞书投递",
    "投递通道",
    "通知未发出",
    "实际通知未发出",
    "用户在飞书端不会看到",
)


RunExecutor = Callable[[RunRequest], RunResult]
FeishuClientFactory = Callable[[FeishuChannelConfig], FeishuClient]


@dataclass(frozen=True)
class DeliveryDecision:
    action: str
    reason: str
    next_attempt_at: float | None = None


class ProactiveService:
    """Background proactive loop for due schedules and Feishu delivery."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        executor: RunExecutor,
        workspace_root: str | None = None,
        feishu_client_factory: FeishuClientFactory | None = None,
    ) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.workspace_root = workspace_root
        self.executor = executor
        self.feishu_client_factory = feishu_client_factory or FeishuClient
        self.store = StateStore(self.state_dir)
        self._state = _ProactiveState(self.state_dir)

    def tick(
        self,
        *,
        now: float | str | None = None,
        schedule_limit: int = 20,
        drain_limit: int = 3,
    ) -> dict[str, Any]:
        self.store.initialize()
        tick_at = _coerce_time(now)
        schedule_results = {
            "watch": ScheduleService(self.state_dir).tick(now=tick_at, limit=schedule_limit, kind="watch"),
            "cron": ScheduleService(self.state_dir).tick(now=tick_at, limit=schedule_limit, kind="cron"),
        }
        drained = DaemonRunner(self.state_dir).drain(
            self._executor_with_workspace,
            limit=drain_limit,
            worker_id=PROACTIVE_WORKER_ID,
        )
        staged = [self.stage_completed_queue_item(item, now=tick_at) for item in drained.get("processed", [])]
        feedback = self.record_feedback_signals(now=tick_at)
        flushed = self.flush_pending(now=tick_at)
        return {
            "kind": "proactive_tick",
            "version": PROACTIVE_STATE_VERSION,
            "scheduled": schedule_results,
            "drained": drained,
            "staged": staged,
            "feedback": feedback,
            "delivery": flushed,
            "status": proactive_status(self.state_dir),
        }

    def stage_completed_queue_item(self, processed: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        if processed.get("status") != "completed":
            return {"status": "skipped", "reason": "queue_not_completed", "queue_id": processed.get("id")}
        queue_id = str(processed.get("id") or "")
        run_id = str(processed.get("run_id") or "")
        if not queue_id or not run_id:
            return {"status": "skipped", "reason": "missing_queue_or_run"}
        queue_item = self.store.get_queue_item(queue_id)
        if not queue_item:
            return {"status": "skipped", "reason": "queue_item_not_found", "queue_id": queue_id}
        metadata = queue_item.get("metadata") if isinstance(queue_item.get("metadata"), dict) else {}
        if metadata.get("source") != "scheduler" or metadata.get("scheduled_kind") not in {"watch", "cron"}:
            return {"status": "skipped", "reason": "not_scheduler_proactive", "queue_id": queue_id}
        delivery_id = _delivery_id(queue_id)
        existing = self._state.delivery(delivery_id)
        if existing and existing.get("status") in {"pending", "sent", "suppressed", "failed"}:
            return {"status": "skipped", "reason": "already_staged", "delivery_id": delivery_id}
        run = self.store.get_run(run_id) or {}
        body = str(run.get("output_text") or "").strip()
        if not body:
            return {"status": "skipped", "reason": "empty_run_output", "queue_id": queue_id, "run_id": run_id}
        timestamp = time.time() if now is None else now
        scheduled_kind = str(metadata.get("scheduled_kind") or "")
        scheduled_item_id = str(metadata.get("scheduled_item_id") or "")
        delivery = {
            "id": delivery_id,
            "queue_id": queue_id,
            "run_id": run_id,
            "scheduled_item_id": scheduled_item_id,
            "scheduled_kind": scheduled_kind,
            "title": str(metadata.get("title") or ""),
            "body": body,
            "status": "pending",
            "attempts": 0,
            "created_at": timestamp,
            "next_attempt_at": timestamp,
            "last_error": "",
            "feedback_recorded": False,
        }
        if scheduled_kind == "watch":
            suppress_reason = _watch_suppression_reason(body)
        else:
            suppress_reason = ""
        if suppress_reason:
            delivery["status"] = "suppressed"
            delivery["suppressed_at"] = timestamp
            delivery["suppress_reason"] = suppress_reason
            self._record_watch_feedback(
                scheduled_item_id,
                outcome="silent",
                note=_compact_text(_strip_silent_marker(body), limit=160),
                now=timestamp,
            )
            self._state.upsert_delivery(delivery)
            return {"status": "suppressed", "reason": suppress_reason, "delivery_id": delivery_id}
        self._state.upsert_delivery(delivery)
        return {"status": "staged", "delivery_id": delivery_id, "scheduled_kind": scheduled_kind}

    def flush_pending(self, *, now: float | None = None, limit: int = 10) -> dict[str, Any]:
        current = time.time() if now is None else now
        settings = load_user_settings(self.state_dir)
        targets = feishu_proactive_targets(self.state_dir)
        target = targets[0] if targets else None
        client = self._feishu_client()
        processed: list[dict[str, Any]] = []
        for delivery in self._state.pending_due(now=current, limit=limit):
            delivery_id = str(delivery["id"])
            if client is None:
                processed.append(self._defer_delivery(delivery, "feishu_not_configured", current + 300))
                continue
            if target is None:
                processed.append(self._defer_delivery(delivery, "feishu_target_not_found", current + 300))
                continue
            decision = _delivery_decision(settings, self._state.read(), target, delivery, now=current)
            if decision.action == "skip":
                delivery.update({"status": "suppressed", "suppress_reason": decision.reason, "suppressed_at": current})
                self._state.upsert_delivery(delivery)
                processed.append({"delivery_id": delivery_id, "status": "suppressed", "reason": decision.reason})
                continue
            if decision.action == "defer":
                processed.append(self._defer_delivery(delivery, decision.reason, decision.next_attempt_at or current + 300))
                continue
            try:
                message_ids = client.send_markdown(
                    str(target["receive_id"]),
                    _delivery_markdown(delivery),
                    receive_id_type=str(target.get("receive_id_type") or "chat_id"),
                )
            except Exception as exc:
                attempts = int(delivery.get("attempts") or 0) + 1
                backoff = _retry_backoff_seconds(settings, attempts)
                status = "failed" if attempts >= _DELIVERY_RETRY_ATTEMPT_LIMIT else "pending"
                delivery.update(
                    {
                        "status": status,
                        "attempts": attempts,
                        "next_attempt_at": current + backoff,
                        "last_error": _compact_error(exc),
                        "updated_at": current,
                    }
                )
                self._state.upsert_delivery(delivery)
                processed.append(
                    {
                        "delivery_id": delivery_id,
                        "status": status,
                        "reason": "send_failed",
                        "attempts": attempts,
                    }
                )
                continue

            delivery.update(
                {
                    "status": "sent",
                    "sent_at": current,
                    "target_key": str(target.get("key") or ""),
                    "receive_id_type": str(target.get("receive_id_type") or "chat_id"),
                    "message_ids": message_ids,
                    "updated_at": current,
                    "last_error": "",
                }
            )
            self._state.upsert_delivery(delivery)
            self._state.record_sent(target, delivery, now=current, settings=settings)
            if delivery.get("scheduled_kind") == "watch":
                self._record_watch_feedback(
                    str(delivery.get("scheduled_item_id") or ""),
                    outcome="notified",
                    note=str(delivery.get("title") or ""),
                    now=current,
                )
                delivery["notified_recorded"] = True
                self._state.upsert_delivery(delivery)
            processed.append({"delivery_id": delivery_id, "status": "sent", "message_count": len(message_ids)})
        return {"processed": processed, "pending": self._state.count(status="pending")}

    def record_feedback_signals(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now
        targets_by_key = {str(target.get("key") or ""): target for target in feishu_proactive_targets(self.state_dir)}
        recorded: list[dict[str, Any]] = []
        for delivery in self._state.sent_without_feedback(limit=50):
            if delivery.get("scheduled_kind") != "watch":
                continue
            sent_at = _optional_float(delivery.get("sent_at")) or 0.0
            if sent_at <= 0 or current - sent_at < 24 * 60 * 60:
                continue
            target = targets_by_key.get(str(delivery.get("target_key") or ""))
            last_interaction = _optional_float(target.get("last_interaction_at")) if target else None
            outcome = "useful" if last_interaction and sent_at <= last_interaction <= sent_at + 5 * 60 else "no_feedback"
            self._record_watch_feedback(
                str(delivery.get("scheduled_item_id") or ""),
                outcome=outcome,
                note=str(delivery.get("title") or ""),
                now=current,
            )
            delivery["feedback_recorded"] = True
            delivery["feedback_outcome"] = outcome
            self._state.upsert_delivery(delivery)
            recorded.append({"delivery_id": delivery["id"], "outcome": outcome})
        return {"recorded": recorded}

    def _executor_with_workspace(self, request: RunRequest) -> RunResult:
        if self.workspace_root and not request.workspace_root:
            request = RunRequest(
                message=request.message,
                state_dir=request.state_dir,
                conversation_id=request.conversation_id,
                mission_id=request.mission_id,
                workspace_root=self.workspace_root,
                prompt_mode=request.prompt_mode,
            )
        return self.executor(request)

    def _defer_delivery(self, delivery: dict[str, Any], reason: str, next_attempt_at: float) -> dict[str, Any]:
        delivery.update(
            {
                "status": "pending",
                "next_attempt_at": float(next_attempt_at),
                "last_defer_reason": reason,
                "updated_at": time.time(),
            }
        )
        self._state.upsert_delivery(delivery)
        return {"delivery_id": delivery["id"], "status": "deferred", "reason": reason, "next_attempt_at": next_attempt_at}

    def _record_watch_feedback(self, item_id: str, *, outcome: str, note: str, now: float) -> None:
        if not item_id:
            return
        try:
            ScheduleService(self.state_dir).record_watch_feedback(item_id, outcome=outcome, note=note, now=now)
        except Exception:
            return

    def _feishu_client(self) -> FeishuClient | None:
        saved = load_feishu_saved_config(self.state_dir)
        if not saved.get("app_id") or not saved.get("app_secret"):
            return None
        config = FeishuChannelConfig(
            state_dir=str(self.state_dir),
            app_id=str(saved.get("app_id") or ""),
            app_secret=str(saved.get("app_secret") or ""),
            domain=str(saved.get("domain") or "feishu"),
            connection=str(saved.get("connection") or "websocket"),
            streaming=bool(saved.get("streaming", True)),
            footer_status=bool(saved.get("footer_status", True)),
            footer_elapsed=bool(saved.get("footer_elapsed", True)),
            thread_session=bool(saved.get("thread_session", True)),
            api_base_url=os.environ.get("FEISHU_API_BASE_URL") or None,
        )
        return self.feishu_client_factory(config)


def proactive_status(state_dir: str | Path) -> dict[str, Any]:
    state = _ProactiveState(state_dir).read()
    deliveries = list(state.get("deliveries", {}).values()) if isinstance(state.get("deliveries"), dict) else []
    counts: dict[str, int] = {}
    for delivery in deliveries:
        status = str(delivery.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    settings = load_user_settings(state_dir)
    targets = feishu_proactive_targets(state_dir)
    recent = sorted(deliveries, key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0), reverse=True)
    return {
        "kind": "proactive_status",
        "version": PROACTIVE_STATE_VERSION,
        "enabled": bool(settings.get("proactive", {}).get("enabled", True)),
        "channel": str(settings.get("proactive", {}).get("channel") or "feishu"),
        "targets": {
            "count": len(targets),
            "primary": _compact_target(targets[0]) if targets else None,
        },
        "counts": counts,
        "pending": counts.get("pending", 0),
        "recent": [_compact_delivery(item) for item in recent[:10]],
    }


class _ProactiveState:
    def __init__(self, state_dir: str | Path) -> None:
        self.path = Path(state_dir).expanduser() / "channels" / "proactive_state.json"

    def read(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(parsed, dict):
            return self._empty()
        parsed.setdefault("version", PROACTIVE_STATE_VERSION)
        parsed.setdefault("deliveries", {})
        parsed.setdefault("target_stats", {})
        return parsed

    def delivery(self, delivery_id: str) -> dict[str, Any] | None:
        deliveries = self.read().get("deliveries")
        if not isinstance(deliveries, dict):
            return None
        item = deliveries.get(delivery_id)
        return dict(item) if isinstance(item, dict) else None

    def upsert_delivery(self, delivery: dict[str, Any]) -> None:
        state = self.read()
        deliveries = state.setdefault("deliveries", {})
        if not isinstance(deliveries, dict):
            deliveries = {}
            state["deliveries"] = deliveries
        item = dict(delivery)
        item["updated_at"] = item.get("updated_at") or time.time()
        deliveries[str(item["id"])] = item
        self.write(state)

    def pending_due(self, *, now: float, limit: int) -> list[dict[str, Any]]:
        deliveries = self.read().get("deliveries")
        if not isinstance(deliveries, dict):
            return []
        pending = [
            dict(item)
            for item in deliveries.values()
            if isinstance(item, dict)
            and item.get("status") == "pending"
            and (_optional_float(item.get("next_attempt_at")) or 0.0) <= now
        ]
        pending.sort(key=lambda item: float(item.get("next_attempt_at") or item.get("created_at") or 0.0))
        return pending[: max(0, int(limit))]

    def sent_without_feedback(self, *, limit: int) -> list[dict[str, Any]]:
        deliveries = self.read().get("deliveries")
        if not isinstance(deliveries, dict):
            return []
        items = [
            dict(item)
            for item in deliveries.values()
            if isinstance(item, dict) and item.get("status") == "sent" and not item.get("feedback_recorded")
        ]
        items.sort(key=lambda item: float(item.get("sent_at") or 0.0))
        return items[: max(0, int(limit))]

    def count(self, *, status: str) -> int:
        deliveries = self.read().get("deliveries")
        if not isinstance(deliveries, dict):
            return 0
        return sum(1 for item in deliveries.values() if isinstance(item, dict) and item.get("status") == status)

    def record_sent(
        self,
        target: dict[str, Any],
        delivery: dict[str, Any],
        *,
        now: float,
        settings: dict[str, Any],
    ) -> None:
        state = self.read()
        stats = state.setdefault("target_stats", {})
        if not isinstance(stats, dict):
            stats = {}
            state["target_stats"] = stats
        target_key = str(target.get("key") or "")
        target_stats = stats.setdefault(target_key, {})
        if not isinstance(target_stats, dict):
            target_stats = {}
            stats[target_key] = target_stats
        item_id = str(delivery.get("scheduled_item_id") or delivery.get("id") or "")
        item_stats = target_stats.setdefault("items", {})
        if not isinstance(item_stats, dict):
            item_stats = {}
            target_stats["items"] = item_stats
        per_item = item_stats.setdefault(item_id, {})
        if not isinstance(per_item, dict):
            per_item = {}
            item_stats[item_id] = per_item
        day_key = _local_day_key(now, settings)
        daily = per_item.setdefault("daily", {})
        if not isinstance(daily, dict):
            daily = {}
            per_item["daily"] = daily
        daily[day_key] = int(daily.get(day_key) or 0) + 1
        target_stats["last_sent_at"] = now
        per_item["last_sent_at"] = now
        self.write(state)

    def write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".proactive_state.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def _empty(self) -> dict[str, Any]:
        return {"version": PROACTIVE_STATE_VERSION, "deliveries": {}, "target_stats": {}}


def _delivery_decision(
    settings: dict[str, Any],
    state: dict[str, Any],
    target: dict[str, Any],
    delivery: dict[str, Any],
    *,
    now: float,
) -> DeliveryDecision:
    proactive = settings.get("proactive") if isinstance(settings.get("proactive"), dict) else {}
    if not proactive.get("enabled", True):
        return DeliveryDecision("skip", "proactive_disabled")
    quiet_until = _quiet_until(settings, now)
    if quiet_until is not None:
        return DeliveryDecision("defer", "quiet_hours", quiet_until)
    grace_s = int(proactive.get("active_conversation_grace_minutes") or 0) * 60
    last_interaction = _optional_float(target.get("last_interaction_at"))
    if grace_s > 0 and last_interaction and now < last_interaction + grace_s:
        return DeliveryDecision("defer", "active_conversation", last_interaction + grace_s)
    target_stats = _target_stats(state, str(target.get("key") or ""))
    item_stats = _item_stats(target_stats, str(delivery.get("scheduled_item_id") or delivery.get("id") or ""))
    cooldown_s = int(proactive.get("cooldown_minutes") or 0) * 60
    last_sent = _optional_float(item_stats.get("last_sent_at") or target_stats.get("last_sent_at"))
    if cooldown_s > 0 and last_sent and now < last_sent + cooldown_s:
        return DeliveryDecision("defer", "cooldown", last_sent + cooldown_s)
    max_daily = int(proactive.get("max_per_day_per_item") or 2)
    day_key = _local_day_key(now, settings)
    daily = item_stats.get("daily") if isinstance(item_stats.get("daily"), dict) else {}
    if int(daily.get(day_key) or 0) >= max_daily:
        return DeliveryDecision("defer", "daily_limit", _next_local_midnight(now, settings))
    return DeliveryDecision("send", "ok")


def _target_stats(state: dict[str, Any], target_key: str) -> dict[str, Any]:
    stats = state.get("target_stats") if isinstance(state.get("target_stats"), dict) else {}
    target = stats.get(target_key) if isinstance(stats.get(target_key), dict) else {}
    return target


def _item_stats(target_stats: dict[str, Any], item_id: str) -> dict[str, Any]:
    items = target_stats.get("items") if isinstance(target_stats.get("items"), dict) else {}
    item = items.get(item_id) if isinstance(items.get(item_id), dict) else {}
    return item


def _quiet_until(settings: dict[str, Any], now: float) -> float | None:
    quiet = settings.get("quiet_hours") if isinstance(settings.get("quiet_hours"), dict) else {}
    if not quiet.get("enabled"):
        return None
    tz = _settings_timezone(quiet)
    current = datetime.fromtimestamp(now, tz)
    start_h, start_m = _parse_hhmm(str(quiet.get("start") or "22:00"))
    end_h, end_m = _parse_hhmm(str(quiet.get("end") or "07:00"))
    current_minute = current.hour * 60 + current.minute
    start_minute = start_h * 60 + start_m
    end_minute = end_h * 60 + end_m
    if start_minute == end_minute:
        return None
    if start_minute < end_minute:
        if start_minute <= current_minute < end_minute:
            return current.replace(hour=end_h, minute=end_m, second=0, microsecond=0).timestamp()
        return None
    if current_minute >= start_minute:
        return (current + timedelta(days=1)).replace(hour=end_h, minute=end_m, second=0, microsecond=0).timestamp()
    if current_minute < end_minute:
        return current.replace(hour=end_h, minute=end_m, second=0, microsecond=0).timestamp()
    return None


def _settings_timezone(settings_or_quiet: dict[str, Any]):
    quiet = settings_or_quiet.get("quiet_hours") if isinstance(settings_or_quiet.get("quiet_hours"), dict) else settings_or_quiet
    name = str(quiet.get("timezone") or "local")
    if name == "local":
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


def _local_day_key(now: float, settings: dict[str, Any]) -> str:
    return datetime.fromtimestamp(now, _settings_timezone(settings)).date().isoformat()


def _next_local_midnight(now: float, settings: dict[str, Any]) -> float:
    current = datetime.fromtimestamp(now, _settings_timezone(settings))
    tomorrow = current.date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=current.tzinfo).timestamp()


def _retry_backoff_seconds(settings: dict[str, Any], attempts: int) -> float:
    proactive = settings.get("proactive") if isinstance(settings.get("proactive"), dict) else {}
    base = int(proactive.get("retry_backoff_minutes") or 5) * 60
    return min(60 * 60, base * (2 ** max(0, attempts - 1)))


def _delivery_id(queue_id: str) -> str:
    return f"delivery_{queue_id}"


def _delivery_markdown(delivery: dict[str, Any]) -> str:
    body = _strip_silent_marker(str(delivery.get("body") or "")).strip()
    title = str(delivery.get("title") or "").strip()
    if title and title.casefold() not in body[:120].casefold():
        return f"### {title}\n\n{body}"
    return body or "（空响应）"


def _is_model_silent(text: str) -> bool:
    normalized = str(text or "").strip().casefold()
    return normalized.startswith("[silent]") or normalized.startswith("silent:") or normalized.startswith("静默:")


def _watch_suppression_reason(text: str) -> str:
    normalized = str(text or "").strip().casefold()
    if not normalized:
        return ""
    if _is_model_silent(text):
        return "model_silent"
    if "[silent]" in normalized or "silent:" in normalized or "静默:" in normalized:
        return "internal_watch_output"
    if any(pattern in normalized for pattern in _INTERNAL_WATCH_OUTPUT_PATTERNS):
        return "internal_watch_output"
    return ""


def _strip_silent_marker(text: str) -> str:
    stripped = str(text or "").strip()
    lowered = stripped.casefold()
    for prefix in ("[silent]", "silent:", "静默:"):
        if lowered.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return stripped


def _coerce_time(value: float | int | str | None) -> float:
    if value is None:
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip()
    if not text or text.casefold() == "now":
        return time.time()
    try:
        return float(text)
    except ValueError:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        return datetime.fromisoformat(normalized).timestamp()


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:240]


def _compact_text(value: Any, *, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _compact_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": target.get("key"),
        "receive_id_type": target.get("receive_id_type"),
        "source": target.get("source"),
        "last_interaction_at": target.get("last_interaction_at"),
    }


def _compact_delivery(delivery: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": delivery.get("id"),
        "status": delivery.get("status"),
        "scheduled_kind": delivery.get("scheduled_kind"),
        "scheduled_item_id": delivery.get("scheduled_item_id"),
        "title": delivery.get("title"),
        "created_at": delivery.get("created_at"),
        "sent_at": delivery.get("sent_at"),
        "next_attempt_at": delivery.get("next_attempt_at"),
        "last_defer_reason": delivery.get("last_defer_reason"),
        "last_error": delivery.get("last_error"),
    }
