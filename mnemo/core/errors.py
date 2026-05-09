from __future__ import annotations

import json
import re


class MnemoError(Exception):
    """Base error for expected Mnemo runtime failures."""


class StateStoreError(MnemoError):
    """Raised when durable state cannot be read or written."""


class ToolError(MnemoError):
    """Raised when a tool call is invalid or fails."""


class NotFoundError(MnemoError):
    """Raised when a requested entity does not exist."""


class DaemonLockError(MnemoError):
    """Raised when another daemon worker owns the state directory lock."""


class ProviderError(MnemoError):
    """Base error for expected provider adapter failures."""


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request exceeds its timeout."""


class ProviderConnectionError(ProviderError):
    """Raised when a provider cannot be reached."""


class ProviderStatusError(ProviderError):
    """Raised when a provider returns a non-success HTTP status."""

    def __init__(self, status_code: int, body: str | None = None) -> None:
        self.status_code = status_code
        self.body = body
        message = f"provider returned HTTP {status_code}"
        detail = _provider_error_detail(body)
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class ProviderPayloadError(ProviderError):
    """Raised when a provider response cannot be parsed or normalized."""


class ProviderSafetyError(ProviderError):
    """Raised when a provider blocks a request with a safety/content filter."""


def _provider_error_detail(body: str | None) -> str | None:
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return _compact_provider_text(body)

    candidates: list[object] = []
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            candidates.extend((error.get("message"), error.get("code")))
        elif isinstance(error, str):
            candidates.append(error)
        candidates.append(parsed.get("message"))

    for value in candidates:
        if isinstance(value, str):
            compacted = _compact_provider_text(value)
            if compacted:
                return compacted
    return None


def _compact_provider_text(value: str) -> str | None:
    compacted = " ".join(value.split())
    if not compacted:
        return None
    compacted = re.sub(r"\b(sk|cpa)-[A-Za-z0-9_-]{8,}\b", r"\1-***", compacted)
    return compacted[:180]
