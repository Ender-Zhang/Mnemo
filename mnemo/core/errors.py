from __future__ import annotations


class MnemoError(Exception):
    """Base error for expected Mnemo runtime failures."""


class StateStoreError(MnemoError):
    """Raised when durable state cannot be read or written."""


class ToolError(MnemoError):
    """Raised when a tool call is invalid or fails."""


class NotFoundError(MnemoError):
    """Raised when a requested entity does not exist."""
