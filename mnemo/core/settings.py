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
    return settings


def save_user_settings(state_dir: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("settings patch must be an object")
    settings = load_user_settings(state_dir)
    if "quiet_hours" in patch:
        if not isinstance(patch["quiet_hours"], dict):
            raise ValueError("quiet_hours must be an object")
        settings["quiet_hours"] = _normalize_quiet_hours({**settings["quiet_hours"], **patch["quiet_hours"]})

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


def _normalize_time(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not _TIME_RE.match(text):
        raise ValueError(f"quiet_hours {name} must be HH:MM")
    hour, minute = text.split(":", 1)
    if int(hour) > 23 or int(minute) > 59:
        raise ValueError(f"quiet_hours {name} must be HH:MM")
    return text
