from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
from typing import Any


SETTINGS_VERSION = "mnemo.settings.v1"

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_DEFAULT_SETTINGS: dict[str, Any] = {
    "version": SETTINGS_VERSION,
    "quiet_hours": {
        "enabled": False,
        "start": "22:00",
        "end": "07:00",
        "timezone": "local",
    },
    "runtime": {
        "provider": "",
        "model": "",
        "base_url": "",
        "api_key_env": "",
        "timeout_s": 30.0,
        "retry_count": 0,
        "retry_backoff_s": 0.0,
        "max_tool_rounds": 12,
    },
    "proactive": {
        "enabled": True,
        "channel": "feishu",
        "cooldown_minutes": 30,
        "active_conversation_grace_minutes": 3,
        "max_per_day_per_item": 2,
        "retry_backoff_minutes": 5,
    },
}


def settings_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "settings.json"


def load_user_settings(state_dir: str | Path) -> dict[str, Any]:
    path = settings_path(state_dir)
    settings = deepcopy(_DEFAULT_SETTINGS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if not isinstance(raw, dict):
        return settings
    if isinstance(raw.get("quiet_hours"), dict):
        try:
            settings["quiet_hours"] = _normalize_quiet_hours(raw["quiet_hours"])
        except ValueError:
            return settings
    if isinstance(raw.get("runtime"), dict):
        try:
            settings["runtime"] = _normalize_runtime_settings({**settings["runtime"], **raw["runtime"]})
        except ValueError:
            return settings
    if isinstance(raw.get("proactive"), dict):
        try:
            settings["proactive"] = _normalize_proactive_settings({**settings["proactive"], **raw["proactive"]})
        except ValueError:
            return settings
    return settings


def save_user_settings(state_dir: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("settings patch must be an object")
    settings = load_user_settings(state_dir)
    if "quiet_hours" in patch:
        if not isinstance(patch["quiet_hours"], dict):
            raise ValueError("quiet_hours must be an object")
        settings["quiet_hours"] = _normalize_quiet_hours({**settings["quiet_hours"], **patch["quiet_hours"]})
    if "runtime" in patch:
        if not isinstance(patch["runtime"], dict):
            raise ValueError("runtime must be an object")
        settings["runtime"] = _normalize_runtime_settings({**settings["runtime"], **patch["runtime"]})
    if "proactive" in patch:
        if not isinstance(patch["proactive"], dict):
            raise ValueError("proactive must be an object")
        settings["proactive"] = _normalize_proactive_settings({**settings["proactive"], **patch["proactive"]})
    if "api_key" in patch:
        raise ValueError("api_key cannot be stored in settings; use api_key_env")

    path = settings_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(settings, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, path)
    return settings


def _normalize_quiet_hours(value: dict[str, Any]) -> dict[str, Any]:
    start = _normalize_time(value.get("start"), "start")
    end = _normalize_time(value.get("end"), "end")
    timezone = str(value.get("timezone") or "local").strip() or "local"
    if len(timezone) > 80:
        raise ValueError("quiet_hours timezone is too long")
    return {
        "enabled": bool(value.get("enabled", False)),
        "start": start,
        "end": end,
        "timezone": timezone,
    }


def _normalize_runtime_settings(value: dict[str, Any]) -> dict[str, Any]:
    if "api_key" in value:
        raise ValueError("runtime api_key cannot be stored; use api_key_env")
    return {
        "provider": _normalize_text(value.get("provider"), "runtime provider", limit=80),
        "model": _normalize_text(value.get("model"), "runtime model", limit=160),
        "base_url": _normalize_text(value.get("base_url"), "runtime base_url", limit=500),
        "api_key_env": _normalize_env_name(value.get("api_key_env")),
        "timeout_s": _normalize_float(value.get("timeout_s"), "runtime timeout_s", minimum=1.0, maximum=600.0),
        "retry_count": _normalize_int(value.get("retry_count"), "runtime retry_count", minimum=0, maximum=10),
        "retry_backoff_s": _normalize_float(
            value.get("retry_backoff_s"),
            "runtime retry_backoff_s",
            minimum=0.0,
            maximum=60.0,
        ),
        "max_tool_rounds": _normalize_int(value.get("max_tool_rounds"), "runtime max_tool_rounds", minimum=1, maximum=64),
    }


def _normalize_proactive_settings(value: dict[str, Any]) -> dict[str, Any]:
    channel = _normalize_text(value.get("channel"), "proactive channel", limit=80) or "feishu"
    if channel not in {"feishu"}:
        raise ValueError("proactive channel must be feishu")
    return {
        "enabled": bool(value.get("enabled", True)),
        "channel": channel,
        "cooldown_minutes": _normalize_int(
            value.get("cooldown_minutes"),
            "proactive cooldown_minutes",
            minimum=0,
            maximum=24 * 60,
        ),
        "active_conversation_grace_minutes": _normalize_int(
            value.get("active_conversation_grace_minutes"),
            "proactive active_conversation_grace_minutes",
            minimum=0,
            maximum=60,
        ),
        "max_per_day_per_item": _normalize_int(
            value.get("max_per_day_per_item"),
            "proactive max_per_day_per_item",
            minimum=1,
            maximum=24,
        ),
        "retry_backoff_minutes": _normalize_int(
            value.get("retry_backoff_minutes"),
            "proactive retry_backoff_minutes",
            minimum=1,
            maximum=24 * 60,
        ),
    }


def _normalize_text(value: Any, name: str, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ValueError(f"{name} is too long")
    return text


def _normalize_env_name(value: Any) -> str:
    text = _normalize_text(value, "runtime api_key_env", limit=120)
    if not text:
        return ""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", text):
        raise ValueError("runtime api_key_env must be an environment variable name")
    return text


def _normalize_float(value: Any, name: str, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return number


def _normalize_int(value: Any, name: str, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _normalize_time(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not _TIME_RE.match(text):
        raise ValueError(f"quiet_hours {name} must be HH:MM")
    hour, minute = text.split(":", 1)
    if int(hour) > 23 or int(minute) > 59:
        raise ValueError(f"quiet_hours {name} must be HH:MM")
    return text
