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
        "auto_dream_status": {"side_effects": "read_only"},
        "save_auto_dream_config": {"side_effects": "writes_auto_dream_config"},
        "tombstones": {"side_effects": "read_only"},
        "stable_create": {"side_effects": "directly_writes_stable_memory_page"},
        "stable_read": {"side_effects": "read_only"},
        "stable_update": {"side_effects": "directly_updates_stable_memory_page"},
        "stable_search": {"side_effects": "read_only"},
        "stable_delete": {"side_effects": "curates_or_physically_deletes_stable_memory_page"},
        "plan_create": {"side_effects": "directly_writes_plan_item"},
        "plan_read": {"side_effects": "read_only"},
        "plan_update": {"side_effects": "directly_updates_plan_item"},
        "plan_list": {"side_effects": "read_only"},
        "plan_complete": {"side_effects": "updates_plan_item_status"},
        "plan_cancel": {"side_effects": "updates_plan_item_status"},
        "plan_archive": {"side_effects": "hides_plan_item_from_default_lists"},
        "plan_proposals": {"side_effects": "read_only"},
        "user_goals": {"side_effects": "read_only"},
        "apply_plan_proposal": {"side_effects": "operator_approved_plan_write"},
        "reject_plan_proposal": {"side_effects": "rejects_pending_plan_write"},
        "update": {"side_effects": "writes_memory_candidates_and_working_notes"},
        "ingest_event": {"side_effects": "writes_source_event_candidates_working_notes_and_plan_proposals"},
        "promote_candidate": {"side_effects": "reviews_candidate_and_may_write_stable_memory_page"},
        "force_promote_candidate": {"side_effects": "admin_override_writes_stable_memory_page"},
        "reject_candidate": {"side_effects": "writes_candidate_status_and_tombstone"},
        "tombstone": {"side_effects": "curates_memory"},
        "forget": {"side_effects": "redacts_memory"},
        "hard_delete": {"side_effects": "physically_deletes_memory_records"},
        "dream_run": {"side_effects": "memory_maintenance_only"},
        "dream_status": {"side_effects": "read_only"},
        "dream_report": {"side_effects": "read_only"},
        "dream_proposals": {"side_effects": "read_only"},
        "apply_dream_proposal": {"side_effects": "applies_operator_approved_memory_reorganization"},
        "reject_dream_proposal": {"side_effects": "rejects_pending_memory_reorganization"},
    },
}


def memory_api_schema() -> dict[str, Any]:
    return deepcopy(_SCHEMA)
