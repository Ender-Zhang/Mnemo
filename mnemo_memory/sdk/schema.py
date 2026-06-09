from __future__ import annotations

from copy import deepcopy
from typing import Any


_SCHEMA: dict[str, Any] = {
    "schema_version": "mnemo_memory.api.v1",
    "title": "Mnemo Memory",
    "description": "Memory-only service API for agent recall, candidate-first learning, curation, and maintenance.",
    "transport": ["python:in_process", "http:json", "mcp:stdio"],
    "methods": {
        "context": {"side_effects": "read_only"},
        "recall": {"side_effects": "read_only"},
        "search": {"side_effects": "read_only"},
        "list": {"side_effects": "read_only"},
        "read": {"side_effects": "read_only"},
        "links": {"side_effects": "read_only"},
        "provenance": {"side_effects": "read_only"},
        "snapshot": {"side_effects": "read_only"},
        "health": {"side_effects": "read_only"},
        "provider_config": {"side_effects": "read_only"},
        "save_provider_config": {"side_effects": "writes_provider_config"},
        "tombstones": {"side_effects": "read_only"},
        "update": {"side_effects": "writes_memory_candidates_and_working_notes"},
        "ingest_event": {"side_effects": "writes_source_event_candidates_and_working_notes"},
        "promote_candidate": {"side_effects": "reviews_candidate_and_may_write_stable_memory_page"},
        "force_promote_candidate": {"side_effects": "admin_override_writes_stable_memory_page"},
        "reject_candidate": {"side_effects": "writes_candidate_status_and_tombstone"},
        "tombstone": {"side_effects": "curates_memory"},
        "forget": {"side_effects": "redacts_memory"},
        "dream_run": {"side_effects": "memory_maintenance_only"},
        "dream_status": {"side_effects": "read_only"},
        "dream_report": {"side_effects": "read_only"},
    },
}


def memory_api_schema() -> dict[str, Any]:
    return deepcopy(_SCHEMA)
