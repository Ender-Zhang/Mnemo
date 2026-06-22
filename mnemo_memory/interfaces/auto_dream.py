from __future__ import annotations

import logging
from pathlib import Path
import threading
import time
from typing import Any

from ..core.jsonutil import dumps, loads
from ..core.log import get_logger, log_event
from ..sdk import MemoryClient


_LOG = get_logger("auto_dream")


AUTO_DREAM_STATUS_FILENAME = "auto-dream-status.json"
AUTO_DREAM_STATUS_VERSION = "mnemo_memory.auto_dream_status.v1"
DEFAULT_AUTO_DREAM_STARTUP_DELAY_S = 300
DEFAULT_AUTO_DREAM_POLL_S = 60
AUTO_DREAM_ERROR_BACKOFF_S = 900

_DREAM_RUN_LOCK = threading.Lock()


class DreamRunBusyError(ValueError):
    pass


def run_dream_with_lock(
    client: MemoryClient,
    *,
    limit: int = 20,
    min_confidence: float = 0.7,
    actions: list[dict[str, Any]] | None = None,
    use_provider: bool = False,
    advanced_dreaming: bool = False,
    execution_policy: str = "semi_auto",
    blocking: bool = True,
) -> dict[str, Any]:
    acquired = _DREAM_RUN_LOCK.acquire(blocking=blocking)
    if not acquired:
        raise DreamRunBusyError("dream run already in progress")
    try:
        return client.dream_run(
            limit=limit,
            min_confidence=min_confidence,
            actions=actions,
            use_provider=use_provider,
            advanced_dreaming=advanced_dreaming,
            execution_policy=execution_policy,
        )
    finally:
        _DREAM_RUN_LOCK.release()


def auto_dream_status(client: MemoryClient, *, running: bool | None = None) -> dict[str, Any]:
    config = client.auto_dream_config()
    status = _load_status(client.state_dir)
    return {
        "kind": "memory_auto_dream_status",
        "version": AUTO_DREAM_STATUS_VERSION,
        "enabled": bool(config["enabled"]),
        "interval_minutes": int(config["interval_minutes"]),
        "limit": int(config["limit"]),
        "min_confidence": float(config["min_confidence"]),
        "local_fallback": bool(config.get("local_fallback", False)),
        "save_path": config["save_path"],
        "status_path": str(_status_path(client.state_dir)),
        "running": bool(_DREAM_RUN_LOCK.locked() if running is None else running),
        "last_outcome": _optional_str(status.get("last_outcome")),
        "last_run_source": _optional_str(status.get("last_run_source")),
        "last_run_mode": _optional_str(status.get("last_run_mode")),
        "last_checked_at": _optional_float(status.get("last_checked_at")),
        "last_config_updated_at": _optional_float(status.get("last_config_updated_at")),
        "last_started_at": _optional_float(status.get("last_started_at")),
        "last_run_at": _optional_float(status.get("last_run_at")),
        "last_finished_at": _optional_float(status.get("last_finished_at")),
        "last_duration_s": _optional_float(status.get("last_duration_s")),
        "next_run_at": _optional_float(status.get("next_run_at")),
        "last_error": _optional_str(status.get("last_error")),
        "last_result": status.get("last_result") if isinstance(status.get("last_result"), dict) else None,
        "last_backlog": status.get("last_backlog") if isinstance(status.get("last_backlog"), dict) else None,
    }


def record_auto_dream_config_change(client: MemoryClient, *, now: float | None = None) -> dict[str, Any]:
    timestamp = time.time() if now is None else float(now)
    config = client.auto_dream_config()
    status = _load_status(client.state_dir)
    status.update(
        {
            "last_outcome": "configured",
            "last_config_updated_at": timestamp,
            "next_run_at": _next_run_at(timestamp, config),
        }
    )
    _save_status(client.state_dir, status)
    return auto_dream_status(client)


def record_manual_dream_run(client: MemoryClient, report: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    timestamp = time.time() if now is None else float(now)
    config = client.auto_dream_config()
    status = _load_status(client.state_dir)
    status.update(
        {
            "last_outcome": "manual_run",
            "last_run_source": "manual",
            "last_run_at": timestamp,
            "last_finished_at": timestamp,
            "last_duration_s": _report_duration(report),
            "last_error": None,
            "last_result": _summarize_report(report),
            "next_run_at": _next_run_at(timestamp, config),
        }
    )
    _save_status(client.state_dir, status)
    return auto_dream_status(client)


class AutoDreamScheduler:
    def __init__(
        self,
        state_dir: str | Path,
        *,
        poll_s: float = DEFAULT_AUTO_DREAM_POLL_S,
        startup_delay_s: float = DEFAULT_AUTO_DREAM_STARTUP_DELAY_S,
        client_factory: type[MemoryClient] = MemoryClient,
    ) -> None:
        self.state_dir = str(state_dir)
        self.poll_s = max(1.0, float(poll_s))
        self.startup_delay_s = max(0.0, float(startup_delay_s))
        self.client_factory = client_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="mnemo-auto-dream", daemon=True)
        self._thread.start()

    def stop(self, *, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout_s)

    def tick_once(self, *, now: float | None = None, force: bool = False) -> dict[str, Any]:
        timestamp = time.time() if now is None else float(now)
        client = self.client_factory(state_dir=self.state_dir)
        config = client.auto_dream_config()
        status = _load_status(self.state_dir)
        next_run_at = _optional_float(status.get("next_run_at"))
        if next_run_at is None and not force:
            status.update(
                {
                    "last_outcome": "scheduled",
                    "next_run_at": timestamp + self.startup_delay_s,
                }
            )
            _save_status(self.state_dir, status)
            return auto_dream_status(client)

        if not force and next_run_at is not None and next_run_at > timestamp:
            return auto_dream_status(client)

        status["last_checked_at"] = timestamp
        if not config["enabled"]:
            return self._skip(client, status, config, timestamp, "disabled")

        dream_status = client.dream_status(limit=int(config["limit"]))
        backlog = dream_status.get("backlog") if isinstance(dream_status.get("backlog"), dict) else {}
        status["last_backlog"] = backlog
        if not _has_backlog(backlog):
            return self._skip(client, status, config, timestamp, "no_backlog")

        provider = client.provider_config()
        use_provider = bool(provider.get("configured"))
        # Without a provider we can still run the deterministic Dream fallback
        # (high-confidence promote, dedupe, low-quality reject, W0 ingest,
        # auto-linking) when the operator opts into local_fallback. Otherwise we
        # keep the safe "wait for a provider" behaviour.
        if not use_provider and not config.get("local_fallback"):
            return self._skip(client, status, config, timestamp, "provider_required")

        run_mode = "model" if use_provider else "local"
        status.update(
            {
                "last_outcome": "running",
                "last_run_source": "auto",
                "last_run_mode": run_mode,
                "last_started_at": timestamp,
                "last_error": None,
            }
        )
        _save_status(self.state_dir, status)
        try:
            report = run_dream_with_lock(
                client,
                limit=int(config["limit"]),
                min_confidence=float(config["min_confidence"]),
                use_provider=use_provider,
                blocking=False,
            )
        except DreamRunBusyError:
            return self._skip(client, status, config, timestamp, "busy", retry_s=min(AUTO_DREAM_ERROR_BACKOFF_S, _interval_s(config)))
        except Exception as exc:  # noqa: BLE001 - persisted operator-facing error.
            finished_at = time.time()
            status.update(
                {
                    "last_outcome": "error",
                    "last_finished_at": finished_at,
                    "last_duration_s": max(0.0, finished_at - timestamp),
                    "last_error": str(exc),
                    "next_run_at": finished_at + min(AUTO_DREAM_ERROR_BACKOFF_S, _interval_s(config)),
                }
            )
            _save_status(self.state_dir, status)
            log_event(_LOG, "auto_dream_tick", level=logging.ERROR, outcome="error", error=str(exc))
            return auto_dream_status(client)

        finished_at = time.time()
        status.update(
            {
                "last_outcome": "ran",
                "last_run_source": "auto",
                "last_run_mode": run_mode,
                "last_run_at": timestamp,
                "last_finished_at": finished_at,
                "last_duration_s": _report_duration(report) or max(0.0, finished_at - timestamp),
                "last_error": None,
                "last_result": _summarize_report(report),
                "next_run_at": finished_at + _interval_s(config),
            }
        )
        _save_status(self.state_dir, status)
        log_event(_LOG, "auto_dream_tick", outcome="ran", mode=run_mode, duration_s=status["last_duration_s"])
        return auto_dream_status(client)

    def _skip(
        self,
        client: MemoryClient,
        status: dict[str, Any],
        config: dict[str, Any],
        timestamp: float,
        outcome: str,
        *,
        retry_s: float | None = None,
    ) -> dict[str, Any]:
        status.update(
            {
                "last_outcome": outcome,
                "last_run_source": "auto",
                "last_finished_at": timestamp,
                "last_duration_s": 0.0,
                "next_run_at": timestamp + (retry_s if retry_s is not None else _interval_s(config)),
            }
        )
        if outcome != "error":
            status["last_error"] = None
        _save_status(self.state_dir, status)
        log_event(_LOG, "auto_dream_tick", outcome=outcome)
        return auto_dream_status(client)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick_once()
            except Exception as exc:  # noqa: BLE001 - background task must persist operator-facing errors.
                timestamp = time.time()
                try:
                    status = _load_status(self.state_dir)
                    status.update(
                        {
                            "last_outcome": "error",
                            "last_checked_at": timestamp,
                            "last_finished_at": timestamp,
                            "last_duration_s": 0.0,
                            "last_error": str(exc),
                            "next_run_at": timestamp + AUTO_DREAM_ERROR_BACKOFF_S,
                        }
                    )
                    _save_status(self.state_dir, status)
                except Exception:
                    pass
            self._stop.wait(self.poll_s)


def _status_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "runs" / AUTO_DREAM_STATUS_FILENAME


def _load_status(state_dir: str | Path) -> dict[str, Any]:
    path = _status_path(state_dir)
    try:
        loaded = loads(path.read_text(encoding="utf-8"), {})
    except (OSError, TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _save_status(state_dir: str | Path, status: dict[str, Any]) -> None:
    path = _status_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "memory_auto_dream_status",
        "version": AUTO_DREAM_STATUS_VERSION,
        **status,
    }
    path.write_text(dumps(payload), encoding="utf-8")


def _has_backlog(counts: dict[str, Any]) -> bool:
    for key in (
        "w0_pending",
        "memory_candidates",
        "draft_candidates",
        "changed_pages",
        "tombstones",
        "review_cards",
        "pending_plan_proposals",
        "changed_plan_items",
    ):
        try:
            if int(counts.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _next_run_at(timestamp: float, config: dict[str, Any]) -> float | None:
    if not config.get("enabled"):
        return None
    return timestamp + _interval_s(config)


def _interval_s(config: dict[str, Any]) -> float:
    try:
        minutes = int(config.get("interval_minutes") or 180)
    except (TypeError, ValueError):
        minutes = 180
    return max(5, minutes) * 60.0


def _summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    actions = result.get("actions") if isinstance(result.get("actions"), dict) else {}
    delta = report.get("delta") if isinstance(report.get("delta"), dict) else {}
    return {
        "id": report.get("id"),
        "duration_s": _report_duration(report),
        "delta_counts": delta.get("counts") if isinstance(delta.get("counts"), dict) else {},
        "action_counts": actions.get("counts") if isinstance(actions.get("counts"), dict) else {},
    }


def _report_duration(report: dict[str, Any]) -> float | None:
    value = report.get("duration_s")
    return _optional_float(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
