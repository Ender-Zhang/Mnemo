"""Lightweight structured logging for mnemo-memory.

The package historically emitted no logs at all, which made silent candidate
rejections and background Dream runs impossible to debug. This module adds a
small, dependency-free structured logger:

- ``get_logger(name)`` returns a namespaced ``logging.Logger``.
- ``log_event(logger, event, level, **fields)`` emits one ``event key=value``
  line so logs stay greppable and machine-parseable.
- ``configure_logging(...)`` wires a stderr handler (and an optional file sink
  under ``<state_dir>/runs/mnemo.log``); it is idempotent and reads
  ``MNEMO_MEMORY_LOG_LEVEL`` / ``MNEMO_MEMORY_LOG_FILE`` by default.

Library code only calls ``get_logger`` / ``log_event``; entry points (CLI,
HTTP serve) call ``configure_logging`` once so importing the package never
installs handlers on its own.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

_ROOT_NAME = "mnemo_memory"
_DEFAULT_LEVEL = "INFO"
_configured = False


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, e.g. ``get_logger("learning")``."""
    suffix = name.strip()
    return logging.getLogger(f"{_ROOT_NAME}.{suffix}" if suffix else _ROOT_NAME)


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Emit a single structured ``event key=value ...`` log line.

    Skips formatting work when the level is disabled. ``None`` fields are
    dropped; values with spaces are quoted so the line stays parseable.
    """
    if not logger.isEnabledFor(level):
        return
    logger.log(level, _format_event(event, fields))


def _format_event(event: str, fields: dict[str, Any]) -> str:
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        text = f"{value:.4g}"
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    if text == "":
        return '""'
    if any(ch.isspace() for ch in text):
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text


class _EventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
        name = record.name
        if name.startswith(f"{_ROOT_NAME}."):
            name = name[len(_ROOT_NAME) + 1:]
        return f"{timestamp} {record.levelname:<5} {name} {record.getMessage()}"


def configure_logging(
    *,
    level: str | int | None = None,
    state_dir: str | Path | None = None,
    log_file: bool | str | None = None,
    force: bool = False,
) -> None:
    """Install handlers on the ``mnemo_memory`` root logger (idempotent)."""
    global _configured
    if _configured and not force:
        return

    root = logging.getLogger(_ROOT_NAME)
    resolved_level = _resolve_level(level)
    root.setLevel(resolved_level)
    root.propagate = False

    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = _EventFormatter()
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    file_path = _resolve_log_file(log_file, state_dir)
    if file_path is not None:
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(file_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            pass

    _configured = True


def _resolve_level(level: str | int | None) -> int:
    raw = level if level is not None else (os.environ.get("MNEMO_MEMORY_LOG_LEVEL") or _DEFAULT_LEVEL)
    if isinstance(raw, int):
        return raw
    resolved = logging.getLevelName(str(raw).strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def _resolve_log_file(log_file: bool | str | None, state_dir: str | Path | None) -> Path | None:
    if isinstance(log_file, str) and log_file.strip():
        return Path(log_file).expanduser()
    env_value = os.environ.get("MNEMO_MEMORY_LOG_FILE")
    enabled = log_file is True or _is_truthy(env_value)
    if isinstance(env_value, str) and env_value.strip() and not _is_bool_token(env_value):
        return Path(env_value).expanduser()
    if enabled and state_dir is not None:
        return Path(state_dir).expanduser() / "runs" / "mnemo.log"
    return None


def _is_truthy(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().casefold() in {"1", "true", "yes", "y", "on"}


def _is_bool_token(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().casefold() in {
        "1", "0", "true", "false", "yes", "no", "y", "n", "on", "off",
    }
