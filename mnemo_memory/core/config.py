from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping


DEFAULT_STATE_DIR = "~/.mnemo-memory"
DEFAULT_PROVIDER = "openai-compatible"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MODEL = "memory-maintainer"


@dataclass(frozen=True)
class MemoryConfig:
    state_dir: str = DEFAULT_STATE_DIR
    provider: str = DEFAULT_PROVIDER
    base_url: str | None = None
    model: str | None = DEFAULT_MODEL
    api_key: str | None = None
    api_key_env: str | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S
    auth_token: str | None = None
    config_path: str | None = None

    def redacted(self) -> dict[str, Any]:
        result = asdict(self)
        result["api_key"] = "***" if self.api_key else None
        result["auth_token"] = "***" if self.auth_token else None
        return result


@dataclass(frozen=True)
class ConfigOverrides:
    state_dir: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    timeout_s: float | None = None
    auth_token: str | None = None
    config_path: str | None = None


def default_config_path(state_dir: str | Path = DEFAULT_STATE_DIR) -> Path:
    return Path(state_dir).expanduser() / "config.json"


def resolve_memory_config(
    overrides: ConfigOverrides | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> MemoryConfig:
    overrides = overrides or ConfigOverrides()
    env = env or os.environ
    config_path = _config_path(overrides, env)
    file_config = _read_config_file(config_path)

    state_dir = _first_str(
        overrides.state_dir,
        env.get("MNEMO_MEMORY_STATE_DIR"),
        file_config.get("state_dir"),
        DEFAULT_STATE_DIR,
    )
    provider = _first_str(
        overrides.provider,
        env.get("MNEMO_MEMORY_PROVIDER"),
        file_config.get("provider"),
        DEFAULT_PROVIDER,
    )
    base_url = _first_optional_str(overrides.base_url, env.get("MNEMO_MEMORY_BASE_URL"), file_config.get("base_url"))
    model = _first_optional_str(overrides.model, env.get("MNEMO_MEMORY_MODEL"), file_config.get("model"), DEFAULT_MODEL)
    api_key_env = _first_optional_str(
        overrides.api_key_env,
        env.get("MNEMO_MEMORY_API_KEY_ENV"),
        file_config.get("api_key_env"),
    )
    api_key = _first_optional_str(
        overrides.api_key,
        env.get(api_key_env) if api_key_env else None,
        env.get("MNEMO_MEMORY_API_KEY"),
        file_config.get("api_key"),
    )
    auth_token = _first_optional_str(
        overrides.auth_token,
        env.get("MNEMO_MEMORY_AUTH_TOKEN"),
        file_config.get("auth_token"),
    )
    timeout_s = _first_float(
        overrides.timeout_s,
        env.get("MNEMO_MEMORY_TIMEOUT_S"),
        file_config.get("timeout_s"),
        DEFAULT_TIMEOUT_S,
    )
    return MemoryConfig(
        state_dir=state_dir,
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        timeout_s=max(0.1, timeout_s),
        auth_token=auth_token,
        config_path=str(config_path) if config_path else None,
    )


def _config_path(overrides: ConfigOverrides, env: Mapping[str, str]) -> Path | None:
    raw_path = overrides.config_path or env.get("MNEMO_MEMORY_CONFIG")
    if raw_path:
        return Path(raw_path).expanduser()
    path = default_config_path(overrides.state_dir or env.get("MNEMO_MEMORY_STATE_DIR") or DEFAULT_STATE_DIR)
    return path if path.exists() else None


def _read_config_file(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_optional_str(*values: Any) -> str | None:
    value = _first_str(*values)
    return value or None


def _first_float(*values: Any) -> float:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return DEFAULT_TIMEOUT_S
