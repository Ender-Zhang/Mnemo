from __future__ import annotations


class MnemoError(Exception):
    """Base error for expected Mnemo Memory failures."""


class StateStoreError(MnemoError):
    """Raised when memory state cannot be read or written."""


class NotFoundError(MnemoError):
    """Raised when a requested memory item does not exist."""


class ProviderError(MnemoError):
    """Raised when memory maintenance provider integration fails."""
