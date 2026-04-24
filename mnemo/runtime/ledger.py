from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.jsonutil import dumps, loads
from ..storage import StateStore


class RunLedger:
    """Append-only event facade over the durable state store."""

    def __init__(self, store: StateStore):
        self.store = store

    def append(self, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        seq = self.store.append_event(run_id, event_type, payload)
        self._append_jsonl(run_id, seq, event_type, payload)
        return seq

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return self.store.get_run_events(run_id)

    def events_since(self, run_id: str, since: int = 0) -> list[dict[str, Any]]:
        return [event for event in self.events(run_id) if int(event["seq"]) > since]

    def latest(self, run_id: str, event_type: str) -> dict[str, Any] | None:
        for event in reversed(self.events(run_id)):
            if event["event_type"] == event_type:
                return event
        return None

    def chat_events(self, run_id: str, since: int = 0) -> list[dict[str, Any]]:
        return [
            event["payload"]
            for event in self.events_since(run_id, since=since)
            if event["event_type"] == "chat.event"
        ]

    def chat_events_after_event_id(self, run_id: str, event_id: str | None) -> list[dict[str, Any]]:
        events = self.chat_events(run_id)
        if not event_id:
            return events
        for index, event in enumerate(events):
            if event.get("event_id") == event_id:
                return events[index + 1 :]
        return events

    def trace_path(self, run_id: str) -> Path:
        return self.store.state_dir / "runs" / f"{run_id}.jsonl"

    def load_trace(self, run_id: str) -> list[dict[str, Any]]:
        path = self.trace_path(run_id)
        if not path.exists():
            return []
        return [loads(line, {}) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _append_jsonl(self, run_id: str, seq: int, event_type: str, payload: dict[str, Any]) -> None:
        path = self.trace_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "seq": seq,
            "event_type": event_type,
            "payload": payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(dumps(record) + "\n")
