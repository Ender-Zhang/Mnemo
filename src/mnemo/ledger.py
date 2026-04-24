from __future__ import annotations

from typing import Any

from .storage import StateStore


class RunLedger:
    """Append-only event facade over the durable state store."""

    def __init__(self, store: StateStore):
        self.store = store

    def append(self, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        return self.store.append_event(run_id, event_type, payload)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return self.store.get_run_events(run_id)
