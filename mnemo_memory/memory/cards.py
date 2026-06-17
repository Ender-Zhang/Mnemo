from __future__ import annotations

from typing import Any

from .query import normalize_memory_dimension
from .utils import _is_tombstone_status, _normalize_space, _status_reason, _truncate

def _compact_working_note(note: dict[str, Any]) -> dict[str, Any]:
    metadata = note.get("metadata") if isinstance(note.get("metadata"), dict) else {}
    return {
        "id": note.get("id"),
        "mission_id": note.get("mission_id"),
        "run_id": note.get("run_id"),
        "summary": _truncate(note.get("content", ""), limit=220),
        "retention": metadata.get("retention") or "ephemeral",
        "dimension": metadata.get("dimension"),
        "scope": metadata.get("scope"),
        "confidence": metadata.get("confidence"),
        "status": note.get("status") or "open",
        "created_at": note.get("created_at"),
    }

def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "run_id": candidate.get("run_id"),
        "claim": _truncate(candidate.get("claim", ""), limit=220),
        "dimension": candidate.get("dimension"),
        "scope": candidate.get("scope"),
        "confidence": candidate.get("confidence"),
        "status": candidate.get("status"),
        "created_at": candidate.get("created_at"),
    }

def _compact_page(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page.get("id"),
        "title": _truncate(page.get("title", ""), limit=96),
        "summary": _truncate(page.get("content", ""), limit=220),
        "scope": page.get("scope"),
        "confidence": page.get("confidence"),
        "status": page.get("status"),
        "updated_at": page.get("updated_at"),
    }

def _compact_tombstone(tombstone: dict[str, Any]) -> dict[str, Any]:
    metadata = tombstone.get("metadata") if isinstance(tombstone.get("metadata"), dict) else {}
    compact = {
        "id": tombstone.get("id"),
        "target_id": tombstone.get("target_id"),
        "target_type": tombstone.get("target_type"),
        "reason": tombstone.get("reason"),
        "summary": _truncate(tombstone.get("summary", ""), limit=180),
        "created_at": tombstone.get("created_at"),
    }
    if metadata.get("replacement_id"):
        compact["replacement_id"] = metadata.get("replacement_id")
        compact["replacement_type"] = metadata.get("replacement_type")
    return compact

def _compact_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run.get("id"),
        "conversation_id": run.get("conversation_id"),
        "mission_id": run.get("mission_id"),
        "status": run.get("status"),
        "input_preview": _truncate(run.get("input_preview", ""), limit=160),
        "created_at": run.get("created_at"),
        "completed_at": run.get("completed_at"),
    }

def _page_result(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "page",
        "id": page["id"],
        "title": page["title"],
        "content": page["content"],
        "scope": page["scope"],
        "confidence": page["confidence"],
        "status": page["status"],
        "source_candidate_id": page.get("source_candidate_id"),
        "created_at": page.get("created_at"),
        "updated_at": page.get("updated_at"),
    }

def _candidate_result(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "candidate",
        "id": candidate["id"],
        "claim": candidate["claim"],
        "dimension": normalize_memory_dimension(candidate.get("dimension"), fallback="context"),
        "scope": candidate["scope"],
        "confidence": candidate["confidence"],
        "status": candidate["status"],
        "evidence": candidate.get("evidence", []),
        "created_at": candidate.get("created_at"),
    }

def _session_result(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "session_message",
        "id": message["id"],
        "message_id": message.get("message_id") or message["id"],
        "conversation_id": message["conversation_id"],
        "mission_id": message["mission_id"],
        "run_id": message["run_id"],
        "role": message["role"],
        "snippet": message["snippet"],
        "created_at": message["created_at"],
    }

def _plan_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "plan_item",
        "id": item["id"],
        "kind": item["kind"],
        "title": item["title"],
        "detail": item.get("detail") or "",
        "scope": item.get("scope") or "global",
        "status": item.get("status") or "open",
        "priority": item.get("priority") or "normal",
        "parent_id": item.get("parent_id"),
        "due_at": item.get("due_at"),
        "source": item.get("source"),
        "source_event_id": item.get("source_event_id"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "completed_at": item.get("completed_at"),
    }

def _candidate_title(candidate: dict[str, Any]) -> str:
    claim = _normalize_space(candidate.get("claim", ""))
    dimension = normalize_memory_dimension(candidate.get("dimension"), fallback="context")
    title_body = claim[:72].rstrip()
    return f"{dimension}: {title_body}"

def _context_card(item: dict[str, Any]) -> dict[str, Any]:
    if item["type"] in {"page", "linked_page"}:
        card = {
            "id": item["id"],
            "type": item["type"],
            "title": item["title"],
            "summary": _truncate(item["content"]),
            "confidence": item.get("confidence"),
            "status": item.get("status"),
        }
        if item["type"] == "linked_page":
            card["relation"] = item.get("relation")
            card["linked_from"] = item.get("linked_from")
            if item.get("why_relevant"):
                card["why_relevant"] = item.get("why_relevant")
            if item.get("association_path"):
                card["association_path"] = item.get("association_path")
        return card
    if item["type"] == "session_message":
        return {
            "id": item["id"],
            "type": "session_message",
            "title": f"{item.get('role', 'message')} message",
            "summary": _truncate(item.get("snippet", "")),
            "conversation_id": item.get("conversation_id"),
            "mission_id": item.get("mission_id"),
            "run_id": item.get("run_id"),
            "message_id": item.get("message_id") or item.get("id"),
            "role": item.get("role"),
            "created_at": item.get("created_at"),
        }
    if item["type"] == "plan_item":
        summary_parts = [item.get("detail") or ""]
        if item.get("due_at"):
            summary_parts.append(f"due_at={item.get('due_at')}")
        return {
            "id": item["id"],
            "type": "plan_item",
            "title": f"{item.get('kind') or 'plan'}: {item.get('title') or item['id']}",
            "summary": _truncate("；".join(part for part in summary_parts if part) or item.get("title", "")),
            "scope": item.get("scope"),
            "status": item.get("status"),
            "priority": item.get("priority"),
            "parent_id": item.get("parent_id"),
            "due_at": item.get("due_at"),
        }
    return {
        "id": item["id"],
        "type": "candidate",
        "title": item.get("dimension") or "memory candidate",
        "summary": _truncate(item["claim"]),
        "confidence": item.get("confidence"),
        "status": item.get("status"),
    }

def _is_prompt_context_item(item: dict[str, Any]) -> bool:
    item_type = str(item.get("type") or "")
    status = str(item.get("status") or "")
    if item_type in {"page", "linked_page"}:
        return status == "active"
    if item_type == "candidate":
        return status == "draft"
    if item_type == "session_message":
        return not _is_tombstone_status(status)
    if item_type == "plan_item":
        return status in {"active", "paused", "open", "doing"}
    return False

def _snapshot_item(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page["id"],
        "title": _truncate(page.get("title", ""), limit=96),
        "summary": _truncate(page.get("content", ""), limit=180),
        "scope": page.get("scope") or "global",
        "confidence": page.get("confidence"),
        "updated_at": page.get("updated_at"),
    }

def _skip_working_note(store: Any, note: dict[str, Any], reason: str) -> dict[str, Any]:
    status = f"skipped:{_status_reason(reason)}"
    store.update_working_note_status(note["id"], status, result={"reason": reason})
    return {
        "note_id": note["id"],
        "status": status,
        "reason": reason,
    }
