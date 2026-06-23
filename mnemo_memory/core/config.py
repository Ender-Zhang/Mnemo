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
DEFAULT_AUTO_DREAM_ENABLED = True
DEFAULT_AUTO_DREAM_INTERVAL_MINUTES = 15
DEFAULT_AUTO_DREAM_LIMIT = 20
DEFAULT_AUTO_DREAM_MIN_CONFIDENCE = 0.7
# Full-auto by default: when no provider is configured the scheduler still runs
# the deterministic consolidation (promote / dedupe / reject / auto-link) instead
# of skipping, so memory candidates don't pile up waiting for manual review.
DEFAULT_AUTO_DREAM_LOCAL_FALLBACK = True
DEFAULT_EMBEDDINGS_ENABLED = False
DEFAULT_QUALITY_WRITE_THRESHOLD = 0.68
DEFAULT_QUALITY_DRAFT_THRESHOLD = 0.5
DEFAULT_PROMOTE_MIN_CONFIDENCE = 0.7
ENV_FILE_KEY = "MNEMO_MEMORY_ENV_FILE"


@dataclass(frozen=True)
class MemoryConfig:
    state_dir: str = DEFAULT_STATE_DIR
    provider: str = DEFAULT_PROVIDER
    base_url: str | None = None
    model: str | None = DEFAULT_MODEL
    api_key: str | None = None
    api_key_env: str | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S
    thinking_enabled: bool = False
    embeddings_enabled: bool = DEFAULT_EMBEDDINGS_ENABLED
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_api_key_env: str | None = None
    auto_dream_enabled: bool = DEFAULT_AUTO_DREAM_ENABLED
    auto_dream_interval_minutes: int = DEFAULT_AUTO_DREAM_INTERVAL_MINUTES
    auto_dream_limit: int = DEFAULT_AUTO_DREAM_LIMIT
    auto_dream_min_confidence: float = DEFAULT_AUTO_DREAM_MIN_CONFIDENCE
    auto_dream_local_fallback: bool = DEFAULT_AUTO_DREAM_LOCAL_FALLBACK
    quality_write_threshold: float = DEFAULT_QUALITY_WRITE_THRESHOLD
    quality_draft_threshold: float = DEFAULT_QUALITY_DRAFT_THRESHOLD
    promote_min_confidence: float = DEFAULT_PROMOTE_MIN_CONFIDENCE
    auth_token: str | None = None
    config_path: str | None = None

    def redacted(self) -> dict[str, Any]:
        result = asdict(self)
        result["api_key"] = "***" if self.api_key else None
        result["embedding_api_key"] = "***" if self.embedding_api_key else None
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
    thinking_enabled: bool | None = None
    embeddings_enabled: bool | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_api_key_env: str | None = None
    auto_dream_enabled: bool | None = None
    auto_dream_interval_minutes: int | None = None
    auto_dream_limit: int | None = None
    auto_dream_min_confidence: float | None = None
    auto_dream_local_fallback: bool | None = None
    quality_write_threshold: float | None = None
    quality_draft_threshold: float | None = None
    promote_min_confidence: float | None = None
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
    env = _env_with_dotenv(env, load_default=env is None)
    config_path = _config_path(overrides, env)
    file_config = _read_config_file(config_path)

    state_dir = _first_str(
        overrides.state_dir,
        file_config.get("state_dir"),
        env.get("MNEMO_MEMORY_STATE_DIR"),
        DEFAULT_STATE_DIR,
    )
    provider = _first_str(
        overrides.provider,
        file_config.get("provider"),
        env.get("MNEMO_MEMORY_PROVIDER"),
        DEFAULT_PROVIDER,
    )
    base_url = _first_optional_str(overrides.base_url, file_config.get("base_url"), env.get("MNEMO_MEMORY_BASE_URL"))
    model = _first_optional_str(overrides.model, file_config.get("model"), env.get("MNEMO_MEMORY_MODEL"), DEFAULT_MODEL)
    api_key_env = _first_optional_str(
        overrides.api_key_env,
        file_config.get("api_key_env"),
        env.get("MNEMO_MEMORY_API_KEY_ENV"),
    )
    api_key = _first_optional_str(
        overrides.api_key,
        file_config.get("api_key"),
        env.get(api_key_env) if api_key_env else None,
        env.get("MNEMO_MEMORY_API_KEY"),
    )
    auth_token = _first_optional_str(
        overrides.auth_token,
        file_config.get("auth_token"),
        env.get("MNEMO_MEMORY_AUTH_TOKEN"),
    )
    timeout_s = _first_float(
        overrides.timeout_s,
        file_config.get("timeout_s"),
        env.get("MNEMO_MEMORY_TIMEOUT_S"),
        DEFAULT_TIMEOUT_S,
    )
    thinking_enabled = _first_bool(
        overrides.thinking_enabled,
        file_config.get("thinking_enabled"),
        env.get("MNEMO_MEMORY_THINKING_ENABLED"),
        False,
    )
    embeddings_enabled = _first_bool(
        overrides.embeddings_enabled,
        file_config.get("embeddings_enabled"),
        env.get("MNEMO_MEMORY_EMBEDDINGS_ENABLED"),
        DEFAULT_EMBEDDINGS_ENABLED,
    )
    embedding_base_url = _first_optional_str(
        overrides.embedding_base_url,
        file_config.get("embedding_base_url"),
        env.get("MNEMO_MEMORY_EMBEDDING_BASE_URL"),
    )
    embedding_model = _first_optional_str(
        overrides.embedding_model,
        file_config.get("embedding_model"),
        env.get("MNEMO_MEMORY_EMBEDDING_MODEL"),
    )
    embedding_api_key_env = _first_optional_str(
        overrides.embedding_api_key_env,
        file_config.get("embedding_api_key_env"),
        env.get("MNEMO_MEMORY_EMBEDDING_API_KEY_ENV"),
    )
    embedding_api_key = _first_optional_str(
        overrides.embedding_api_key,
        file_config.get("embedding_api_key"),
        env.get(embedding_api_key_env) if embedding_api_key_env else None,
        env.get("MNEMO_MEMORY_EMBEDDING_API_KEY"),
    )
    auto_dream_enabled = _first_bool(
        overrides.auto_dream_enabled,
        file_config.get("auto_dream_enabled"),
        env.get("MNEMO_MEMORY_AUTO_DREAM_ENABLED"),
        DEFAULT_AUTO_DREAM_ENABLED,
    )
    auto_dream_interval_minutes = _first_int(
        overrides.auto_dream_interval_minutes,
        file_config.get("auto_dream_interval_minutes"),
        env.get("MNEMO_MEMORY_AUTO_DREAM_INTERVAL_MINUTES"),
        DEFAULT_AUTO_DREAM_INTERVAL_MINUTES,
    )
    auto_dream_limit = _first_int(
        overrides.auto_dream_limit,
        file_config.get("auto_dream_limit"),
        env.get("MNEMO_MEMORY_AUTO_DREAM_LIMIT"),
        DEFAULT_AUTO_DREAM_LIMIT,
    )
    auto_dream_min_confidence = _first_float(
        overrides.auto_dream_min_confidence,
        file_config.get("auto_dream_min_confidence"),
        env.get("MNEMO_MEMORY_AUTO_DREAM_MIN_CONFIDENCE"),
        DEFAULT_AUTO_DREAM_MIN_CONFIDENCE,
    )
    auto_dream_local_fallback = _first_bool(
        overrides.auto_dream_local_fallback,
        file_config.get("auto_dream_local_fallback"),
        env.get("MNEMO_MEMORY_AUTO_DREAM_LOCAL_FALLBACK"),
        DEFAULT_AUTO_DREAM_LOCAL_FALLBACK,
    )
    quality_write_threshold = _first_float(
        overrides.quality_write_threshold,
        file_config.get("quality_write_threshold"),
        env.get("MNEMO_MEMORY_QUALITY_WRITE_THRESHOLD"),
        DEFAULT_QUALITY_WRITE_THRESHOLD,
    )
    quality_draft_threshold = _first_float(
        overrides.quality_draft_threshold,
        file_config.get("quality_draft_threshold"),
        env.get("MNEMO_MEMORY_QUALITY_DRAFT_THRESHOLD"),
        DEFAULT_QUALITY_DRAFT_THRESHOLD,
    )
    promote_min_confidence = _first_float(
        overrides.promote_min_confidence,
        file_config.get("promote_min_confidence"),
        env.get("MNEMO_MEMORY_PROMOTE_MIN_CONFIDENCE"),
        DEFAULT_PROMOTE_MIN_CONFIDENCE,
    )
    quality_write_threshold = max(0.0, min(1.0, quality_write_threshold))
    quality_draft_threshold = max(0.0, min(quality_write_threshold, quality_draft_threshold))
    return MemoryConfig(
        state_dir=state_dir,
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        timeout_s=max(0.1, timeout_s),
        thinking_enabled=thinking_enabled,
        embeddings_enabled=embeddings_enabled,
        embedding_base_url=embedding_base_url,
        embedding_model=embedding_model,
        embedding_api_key=embedding_api_key,
        embedding_api_key_env=embedding_api_key_env,
        auto_dream_enabled=auto_dream_enabled,
        auto_dream_interval_minutes=max(5, auto_dream_interval_minutes),
        auto_dream_limit=max(1, min(50, auto_dream_limit)),
        auto_dream_min_confidence=max(0.0, min(1.0, auto_dream_min_confidence)),
        auto_dream_local_fallback=auto_dream_local_fallback,
        quality_write_threshold=quality_write_threshold,
        quality_draft_threshold=quality_draft_threshold,
        promote_min_confidence=max(0.0, min(1.0, promote_min_confidence)),
        auth_token=auth_token,
        config_path=str(config_path) if config_path else None,
    )


_EFFECTIVE_CONFIG_FIELDS: list[tuple[str, str, Any]] = [
    ("provider", "MNEMO_MEMORY_PROVIDER", DEFAULT_PROVIDER),
    ("base_url", "MNEMO_MEMORY_BASE_URL", None),
    ("model", "MNEMO_MEMORY_MODEL", DEFAULT_MODEL),
    ("api_key_env", "MNEMO_MEMORY_API_KEY_ENV", None),
    ("timeout_s", "MNEMO_MEMORY_TIMEOUT_S", DEFAULT_TIMEOUT_S),
    ("thinking_enabled", "MNEMO_MEMORY_THINKING_ENABLED", False),
    ("embeddings_enabled", "MNEMO_MEMORY_EMBEDDINGS_ENABLED", DEFAULT_EMBEDDINGS_ENABLED),
    ("embedding_base_url", "MNEMO_MEMORY_EMBEDDING_BASE_URL", None),
    ("embedding_model", "MNEMO_MEMORY_EMBEDDING_MODEL", None),
    ("auto_dream_enabled", "MNEMO_MEMORY_AUTO_DREAM_ENABLED", DEFAULT_AUTO_DREAM_ENABLED),
    ("auto_dream_interval_minutes", "MNEMO_MEMORY_AUTO_DREAM_INTERVAL_MINUTES", DEFAULT_AUTO_DREAM_INTERVAL_MINUTES),
    ("auto_dream_local_fallback", "MNEMO_MEMORY_AUTO_DREAM_LOCAL_FALLBACK", DEFAULT_AUTO_DREAM_LOCAL_FALLBACK),
    ("quality_write_threshold", "MNEMO_MEMORY_QUALITY_WRITE_THRESHOLD", DEFAULT_QUALITY_WRITE_THRESHOLD),
    ("quality_draft_threshold", "MNEMO_MEMORY_QUALITY_DRAFT_THRESHOLD", DEFAULT_QUALITY_DRAFT_THRESHOLD),
    ("promote_min_confidence", "MNEMO_MEMORY_PROMOTE_MIN_CONFIDENCE", DEFAULT_PROMOTE_MIN_CONFIDENCE),
]


def describe_effective_config(state_dir: str | Path = DEFAULT_STATE_DIR) -> dict[str, Any]:
    """Report each config field's effective value and which layer it came from.

    Precedence mirrors ``resolve_memory_config`` for a running service (no CLI
    overrides): ``config.json`` > ``.env`` / process env > built-in default.
    Secrets are reported as a configured/not-configured boolean, never echoed.
    """
    env = _env_with_dotenv(None, load_default=True)
    config_path = default_config_path(state_dir)
    config_path = config_path if config_path.exists() else None
    file_config = _read_config_file(config_path)

    rows: list[dict[str, Any]] = []
    for field, env_key, default in _EFFECTIVE_CONFIG_FIELDS:
        if _present(file_config.get(field)):
            value, source = file_config.get(field), "config.json"
        elif _present(env.get(env_key)):
            value, source = env.get(env_key), "env / .env"
        else:
            value, source = default, "default"
        rows.append({"field": field, "value": _display_config_value(value), "source": source})

    resolved = resolve_memory_config(ConfigOverrides(state_dir=str(state_dir)), env=env)
    rows.append({"field": "api_key", "value": "已配置" if resolved.api_key else "未设置", "source": "secret"})
    rows.append({"field": "embedding_api_key", "value": "已配置" if resolved.embedding_api_key else "未设置", "source": "secret"})

    return {
        "kind": "memory_effective_config",
        "version": "mnemo_memory.effective_config.v1",
        "config_path": str(config_path) if config_path else None,
        "rows": rows,
    }


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _display_config_value(value: Any) -> str:
    if value is None or value == "":
        return "（未设置）"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _config_path(overrides: ConfigOverrides, env: Mapping[str, str]) -> Path | None:
    raw_path = overrides.config_path or env.get("MNEMO_MEMORY_CONFIG")
    if raw_path:
        return Path(raw_path).expanduser()
    path = default_config_path(overrides.state_dir or env.get("MNEMO_MEMORY_STATE_DIR") or DEFAULT_STATE_DIR)
    return path if path.exists() else None


def _env_with_dotenv(env: Mapping[str, str] | None, *, load_default: bool) -> dict[str, str]:
    raw_env = os.environ if env is None else env
    env_values = {str(key): str(value) for key, value in raw_env.items()}
    env_file = _dotenv_path(env_values, load_default=load_default)
    file_values = _read_env_file(env_file)
    return {**file_values, **env_values}


def _dotenv_path(env: Mapping[str, str], *, load_default: bool) -> Path | None:
    raw_path = env.get(ENV_FILE_KEY)
    if raw_path:
        return Path(raw_path).expanduser()
    if load_default:
        return Path.cwd() / ".env"
    return None


def _read_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").strip()
        if "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue
        values[key] = _strip_env_value(raw_value.strip())
    return values


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


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
    default = values[-1] if values else DEFAULT_TIMEOUT_S
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    try:
        return float(default)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S


def _first_int(*values: Any) -> int:
    default = values[-1] if values else 0
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    try:
        return int(default)
    except (TypeError, ValueError):
        return 0


def _first_bool(*values: Any) -> bool:
    for value in values:
        parsed = _parse_bool(value)
        if parsed is not None:
            return parsed
    return False


def _parse_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if normalized in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "disabled", "disable"}:
            return False
    return None
