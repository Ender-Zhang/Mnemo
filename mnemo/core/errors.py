from __future__ import annotations


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
        super().__init__(f"provider returned HTTP {status_code}")


class ProviderPayloadError(ProviderError):
    """Raised when a provider response cannot be parsed or normalized."""
