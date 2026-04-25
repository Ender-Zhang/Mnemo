from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

from ..core.jsonutil import dumps
from ..memory import MemoryEngine
from ..storage import StateStore

CAPSULE_VERSION = "mnemo.context_capsule.v1"
DEFAULT_RETURN_FIELDS = (
    "summary",
    "evidence",
    "files_changed",
    "open_questions",
    "confidence",
)
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b[A-Z][A-Z0-9_]{15,}\b"),
)
_SENSITIVE_TITLE_MARKERS = ("relationship", "relationships", "boundary", "boundaries", "identity")


class ContextCapsuleBuilder:
    """Build a compact external-runtime context without exposing raw Mnemo state."""

    def __init__(self, store: StateStore):
        self.store = store

    def build(
        self,
        task: str,
        *,
        runtime: str = "external",
        agent_type: str = "general",
        requested_pages: list[str] | tuple[str, ...] | None = None,
        allowed_pages: list[str] | tuple[str, ...] | None = None,
        conversation_id: str | None = None,
        mission_id: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        task_text = _required_text(task, "task")
        requested = _unique_strings(requested_pages)
        allowed = set(_unique_strings(allowed_pages))
        pages = self.store.list_memory_pages(status="active", limit=max(1, int(limit)))
        page_by_id = {str(page.get("id")): page for page in pages}

        selected_pointers = _selected_pointers(pages, requested, allowed=allowed, limit=max(1, int(limit)))
        allowed_page_cards = [
            _allowed_page_card(page_by_id[page_id])
            for page_id in requested
            if page_id in allowed and page_id in page_by_id
        ]
        unresolved = [
            {"id": page_id, "status": "not_found_or_inactive"}
            for page_id in requested
            if page_id not in page_by_id
        ]
        blocked = [
            {"id": page_id, "status": "pointer_only", "reason": "not_in_allowed_pages"}
            for page_id in requested
            if page_id in page_by_id and page_id not in allowed
        ]
        capsule = {
            "kind": "context_capsule",
            "version": CAPSULE_VERSION,
            "runtime": _compact_text(runtime, limit=64) or "external",
            "agent_type": _compact_text(agent_type, limit=64) or "general",
            "task": task_text,
            "mission_brief": self._mission_brief(conversation_id=conversation_id, mission_id=mission_id),
            "persona_min": _persona_min(pages),
            "memory_pointers": selected_pointers,
            "allowed_pages": allowed_page_cards,
            "requested_pages": {
                "ids": requested,
                "blocked": blocked,
                "unresolved": unresolved,
            },
            "tool_policy": {
                "direct_mnemo_writes": False,
                "direct_memory_skill_tool_mutation": False,
                "recommended_bridge": "mnemo_mcp",
            },
            "retention_policy": {
                "fresh_context": True,
                "no_long_term_external_retention": True,
                "do_not_store_personal_context": True,
            },
            "return_contract": {
                "required_fields": list(DEFAULT_RETURN_FIELDS),
                "side_effects": "proposals_only",
                "accepted_event_types": [
                    "external.result.proposed",
                    "artifact.patch.proposed",
                    "memory.observation.proposed",
                    "skill.patch.proposed",
                ],
            },
            "boundary": {
                "disclosure": "l1_pointers_plus_allowed_summaries",
                "full_soul": False,
                "full_memory_pages": False,
                "full_session_transcripts": False,
                "raw_tool_schemas": False,
            },
        }
        capsule["capsule_id"] = _capsule_id(capsule)
        capsule["text"] = _capsule_text(capsule)
        return capsule

    def _mission_brief(self, *, conversation_id: str | None, mission_id: str | None) -> dict[str, Any]:
        mission = self.store.get_mission(mission_id) if mission_id else None
        if not mission and conversation_id:
            missions = self.store.list_missions(conversation_id=conversation_id, status="active", limit=1)
            mission = missions[0] if missions else None
        if not mission:
            missions = self.store.list_missions(status="active", limit=1)
            mission = missions[0] if missions else None
        if not mission:
            return {
                "mission_id": None,
                "conversation_id": conversation_id,
                "status": "unspecified",
                "brief": "External runtime handoff.",
                "checkpoint": {},
            }
        checkpoint = mission.get("checkpoint") if isinstance(mission.get("checkpoint"), dict) else {}
        return {
            "mission_id": mission.get("id"),
            "conversation_id": mission.get("conversation_id") or conversation_id,
            "status": mission.get("status"),
            "brief": _compact_text(mission.get("brief"), limit=240),
            "checkpoint": _compact_mapping(checkpoint, limit=6),
        }


def build_context_capsule(
    state_dir: str | Path,
    task: str,
    *,
    runtime: str = "external",
    agent_type: str = "general",
    requested_pages: list[str] | tuple[str, ...] | None = None,
    allowed_pages: list[str] | tuple[str, ...] | None = None,
    conversation_id: str | None = None,
    mission_id: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    store = StateStore(state_dir)
    store.initialize()
    return ContextCapsuleBuilder(store).build(
        task,
        runtime=runtime,
        agent_type=agent_type,
        requested_pages=requested_pages,
        allowed_pages=allowed_pages,
        conversation_id=conversation_id,
        mission_id=mission_id,
        limit=limit,
    )


def _selected_pointers(
    pages: list[dict[str, Any]],
    requested: list[str],
    *,
    allowed: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    page_by_id = {str(page.get("id")): page for page in pages}
    selected: list[dict[str, Any]] = []
    for page_id in requested:
        page = page_by_id.get(page_id)
        if page:
            selected.append(_memory_pointer(page, requested=True, allowed=page_id in allowed))
    if len(selected) < limit:
        seen = {str(item.get("id")) for item in selected}
        for page in pages:
            page_id = str(page.get("id"))
            if page_id not in seen and not _is_sensitive_page(page):
                selected.append(_memory_pointer(page, requested=False, allowed=False))
                seen.add(page_id)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _memory_pointer(page: dict[str, Any], *, requested: bool, allowed: bool) -> dict[str, Any]:
    restricted = _is_sensitive_page(page) and not allowed
    return {
        "id": page.get("id"),
        "title": "[restricted]" if restricted else _compact_text(page.get("title"), limit=120),
        "scope": None if restricted else page.get("scope"),
        "confidence": None if restricted else page.get("confidence"),
        "updated_at": page.get("updated_at"),
        "requested": requested,
        "disclosure": "restricted_pointer" if restricted else "pointer_only",
    }


def _allowed_page_card(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page.get("id"),
        "title": _compact_text(page.get("title"), limit=120),
        "summary": _compact_text(page.get("content"), limit=220),
        "scope": page.get("scope"),
        "confidence": page.get("confidence"),
        "status": page.get("status"),
        "disclosure": "bounded_summary",
    }


def _is_sensitive_page(page: dict[str, Any]) -> bool:
    title = str(page.get("title") or "").casefold()
    return any(marker in title for marker in _SENSITIVE_TITLE_MARKERS)


def _persona_min(pages: list[dict[str, Any]], *, limit: int = 4) -> dict[str, Any]:
    preference_cards: list[dict[str, Any]] = []
    for page in pages:
        title = str(page.get("title") or "")
        if "preference" not in title.casefold():
            continue
        preference_cards.append(
            {
                "id": page.get("id"),
                "title": _compact_text(title, limit=120),
                "summary": _compact_text(page.get("content"), limit=160),
            }
        )
        if len(preference_cards) >= limit:
            break
    return {
        "disclosure": "minimum_communication_preferences",
        "preferences": preference_cards,
    }


def _capsule_text(capsule: dict[str, Any]) -> str:
    lines = [
        "ContextCapsule",
        f"runtime: {capsule['runtime']}",
        f"agent_type: {capsule['agent_type']}",
        f"task: {capsule['task']}",
        f"mission: {capsule['mission_brief']['brief']}",
        "boundaries: proposals_only; no direct Mnemo memory/skill/tool mutation",
        "return_contract: " + ", ".join(capsule["return_contract"]["required_fields"]),
    ]
    if capsule["memory_pointers"]:
        lines.append("memory_pointers:")
        for pointer in capsule["memory_pointers"]:
            lines.append(f"- {pointer['id']}: {pointer['title']} ({pointer['disclosure']})")
    if capsule["allowed_pages"]:
        lines.append("allowed_page_summaries:")
        for page in capsule["allowed_pages"]:
            lines.append(f"- {page['id']}: {page['summary']}")
    return "\n".join(lines)


def _compact_mapping(value: dict[str, Any], *, limit: int) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= limit:
            result["..."] = "truncated"
            break
        result[str(key)] = _compact_text(item, limit=160)
    return result


def _compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."


def _required_text(value: Any, field: str) -> str:
    text = _compact_text(value, limit=1200)
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _unique_strings(values: list[str] | tuple[str, ...] | None) -> list[str]:
    result: list[str] = []
    for value in values or ():
        for part in str(value).split(","):
            text = part.strip()
            if text and text not in result:
                result.append(text)
    return result


def _capsule_id(capsule: dict[str, Any]) -> str:
    payload = {key: value for key, value in capsule.items() if key not in {"capsule_id", "text"}}
    digest = hashlib.sha256(dumps(payload).encode("utf-8")).hexdigest()[:16]
    return f"capsule_{digest}"
