from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from ..core.jsonutil import dumps
from ..core.log import get_logger, log_event
from .constants import PRIVATE_DELETE_RULE, PRIVATE_DELETE_SUMMARY, PRIVATE_DELETE_TOMBSTONE_REASON
from .utils import (
    _curation_status,
    _is_harmful_reason,
    _is_private_delete_status,
    _normalize_space,
    _normalize_tombstone_target_type,
    _status_reason,
    _truncate,
)
from .wiki import materialize_memory_page, remove_memory_page_wiki_files


_LOG = get_logger("curation")


class MemoryCurationMixin:
    def tombstone_memory(
        self,
        memory_id: str,
        reason: str,
        *,
        target_type: str = "auto",
        replacement_id: str | None = None,
        eval_run_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_target_type = _normalize_tombstone_target_type(target_type)
        reason_text = _normalize_space(reason) or "unspecified"
        reason_slug = _status_reason(reason_text)
        status = _curation_status(reason_text)
        log_event(_LOG, "tombstone", memory_id=memory_id, target_type=normalized_target_type, reason=reason_text)
        replacement = self._resolve_replacement(replacement_id)
        if replacement and str(replacement["id"]) == str(memory_id):
            raise ValueError(f"Replacement memory item must differ from curated item: {memory_id}")
        if normalized_target_type in {"auto", "page"}:
            page = self._get_page(memory_id)
            if page:
                summary = _truncate(page.get("content", ""), limit=180)
                source_run_id = self._page_source_run_id(page)
                update_page_status = getattr(self.store, "update_memory_page_status", None)
                if not update_page_status:
                    raise ValueError("memory page tombstone is not supported by this store")
                update_page_status(memory_id, status)
                replacement_link_id = self._link_replacement(memory_id, replacement)
                tombstone_id = self.store.add_memory_tombstone(
                    memory_id,
                    "page",
                    reason_text,
                    summary=summary,
                    metadata=_curation_metadata(
                        title=page.get("title"),
                        scope=page.get("scope"),
                        previous_status=page.get("status"),
                        replacement=replacement,
                        replacement_link_id=replacement_link_id,
                    ),
                )
                eval_case = self._create_harmful_eval_case(
                    memory_id,
                    "page",
                    reason_text,
                    status=status,
                    tombstone_id=tombstone_id,
                    summary=summary,
                    eval_run_id=eval_run_id,
                    source_run_id=source_run_id,
                    scope=page.get("scope"),
                    replacement=replacement,
                )
                updated_page = self._get_page(memory_id)
                wiki = materialize_memory_page(self.store.state_dir, updated_page) if updated_page else None
                return {
                    "memory_id": memory_id,
                    "target_type": "page",
                    "status": status,
                    "reason": reason_text,
                    "reason_slug": reason_slug,
                    "tombstone_id": tombstone_id,
                    "replacement": replacement,
                    "replacement_link_id": replacement_link_id,
                    "eval_case": eval_case,
                    "memory": updated_page,
                    "wiki": wiki,
                }

        if normalized_target_type in {"auto", "candidate"}:
            candidate = self._get_candidate(memory_id)
            if candidate:
                summary = _truncate(candidate.get("claim", ""), limit=180)
                source_run_id = candidate.get("run_id")
                self.store.update_memory_candidate_status(memory_id, status)
                replacement_link_id = self._link_replacement(memory_id, replacement)
                tombstone_id = self.store.add_memory_tombstone(
                    memory_id,
                    "candidate",
                    reason_text,
                    summary=summary,
                    evidence_run_id=source_run_id,
                    metadata=_curation_metadata(
                        dimension=candidate.get("dimension"),
                        scope=candidate.get("scope"),
                        previous_status=candidate.get("status"),
                        replacement=replacement,
                        replacement_link_id=replacement_link_id,
                    ),
                )
                eval_case = self._create_harmful_eval_case(
                    memory_id,
                    "candidate",
                    reason_text,
                    status=status,
                    tombstone_id=tombstone_id,
                    summary=summary,
                    eval_run_id=eval_run_id,
                    source_run_id=source_run_id,
                    dimension=candidate.get("dimension"),
                    scope=candidate.get("scope"),
                    replacement=replacement,
                )
                return {
                    "memory_id": memory_id,
                    "target_type": "candidate",
                    "status": status,
                    "reason": reason_text,
                    "reason_slug": reason_slug,
                    "tombstone_id": tombstone_id,
                    "replacement": replacement,
                    "replacement_link_id": replacement_link_id,
                    "eval_case": eval_case,
                    "memory": self._get_candidate(memory_id),
                }

        raise ValueError(f"Memory item not found for tombstone: {memory_id}")

    def private_delete_memory(
        self,
        memory_id: str,
        reason: str = PRIVATE_DELETE_TOMBSTONE_REASON,
        *,
        target_type: str = "auto",
    ) -> dict[str, Any]:
        normalized_target_type = _normalize_tombstone_target_type(target_type)
        reason_text = _normalize_space(reason) or PRIVATE_DELETE_TOMBSTONE_REASON
        log_event(_LOG, "private_delete", level=logging.WARNING, memory_id=memory_id, target_type=normalized_target_type, reason=reason_text)
        if normalized_target_type in {"auto", "page"}:
            page = self._get_page(memory_id)
            if page:
                return self._private_delete_page(page, reason_text, redact_source_candidate=True)

        if normalized_target_type in {"auto", "candidate"}:
            candidate = self._get_candidate(memory_id)
            if candidate:
                return self._private_delete_candidate(candidate, reason_text, redact_promoted_pages=True)

        raise ValueError(f"Memory item not found for private delete: {memory_id}")

    def hard_delete_memory(
        self,
        memory_id: str | None = None,
        *,
        target_type: str = "auto",
        tombstone_id: str | None = None,
        delete_related: bool = True,
    ) -> dict[str, Any]:
        tombstone = self.store.get_memory_tombstone(tombstone_id) if tombstone_id else None
        if tombstone_id and not tombstone:
            raise ValueError(f"Memory tombstone not found for hard delete: {tombstone_id}")

        target_id = _normalize_space(str(memory_id or ""))
        if not target_id and tombstone:
            target_id = _normalize_space(str(tombstone.get("target_id") or ""))
        if not target_id:
            raise ValueError("memory_id or tombstone_id is required for hard delete")

        requested_type = target_type
        if target_type == "auto" and tombstone:
            requested_type = str(tombstone.get("target_type") or "auto")
        normalized_target_type = _normalize_tombstone_target_type(requested_type)

        pages: dict[str, dict[str, Any]] = {}
        candidates: dict[str, dict[str, Any]] = {}
        if normalized_target_type in {"auto", "page"}:
            page = self._get_page(target_id)
            if page:
                pages[target_id] = page
        if normalized_target_type in {"auto", "candidate"}:
            candidate = self._get_candidate(target_id)
            if candidate:
                candidates[target_id] = candidate

        if not pages and not candidates and not tombstone:
            raise ValueError(f"Memory item not found for hard delete: {target_id}")

        if delete_related:
            for page in list(pages.values()):
                source_candidate_id = _normalize_space(str(page.get("source_candidate_id") or ""))
                if source_candidate_id and source_candidate_id not in candidates:
                    source_candidate = self._get_candidate(source_candidate_id)
                    if source_candidate:
                        candidates[source_candidate_id] = source_candidate
                list_backlinks = getattr(self.store, "list_memory_backlinks", None)
                if list_backlinks:
                    for link in list_backlinks(str(page.get("id") or "")):
                        if link.get("relation") != "promoted_to":
                            continue
                        linked_candidate_id = _normalize_space(str(link.get("source_id") or ""))
                        if linked_candidate_id and linked_candidate_id not in candidates:
                            linked_candidate = self._get_candidate(linked_candidate_id)
                            if linked_candidate:
                                candidates[linked_candidate_id] = linked_candidate
            for candidate_id in list(candidates):
                for page_id in self._promoted_page_ids(candidate_id):
                    if page_id not in pages:
                        page = self._get_page(page_id)
                        if page:
                            pages[page_id] = page

        counts = {"candidates": 0, "pages": 0, "links": 0, "tombstones": 0}
        removed_wiki: list[str] = []
        for page_id in sorted(pages):
            removed_wiki.extend(remove_memory_page_wiki_files(self.store.state_dir, page_id))
            _add_counts(counts, self.store.delete_memory_page(page_id))
        for candidate_id in sorted(candidates):
            _add_counts(counts, self.store.delete_memory_candidate(candidate_id))
        if tombstone_id:
            counts["tombstones"] += self.store.delete_memory_tombstone(tombstone_id)

        return {
            "kind": "memory_hard_delete",
            "memory_id": target_id,
            "target_type": normalized_target_type if normalized_target_type != "auto" else _resolved_target_type(pages, candidates),
            "tombstone_id": tombstone_id,
            "delete_related": delete_related,
            "deleted": any(counts.values()) or bool(removed_wiki),
            "counts": counts,
            "deleted_pages": sorted(pages),
            "deleted_candidates": sorted(candidates),
            "removed_wiki": removed_wiki,
        }

    def _resolve_replacement(self, replacement_id: str | None) -> dict[str, Any] | None:
        replacement_value = _normalize_space(str(replacement_id or ""))
        if not replacement_value:
            return None
        if self._get_page(replacement_value):
            return {"id": replacement_value, "target_type": "page"}
        if self._get_candidate(replacement_value):
            return {"id": replacement_value, "target_type": "candidate"}
        raise ValueError(f"Replacement memory item not found: {replacement_value}")

    def _link_replacement(self, memory_id: str, replacement: dict[str, Any] | None) -> str | None:
        if not replacement:
            return None
        if str(replacement["id"]) == str(memory_id):
            raise ValueError(f"Replacement memory item must differ from curated item: {memory_id}")
        add_link = getattr(self.store, "add_memory_link", None)
        if not add_link:
            return None
        return add_link(memory_id, str(replacement["id"]), "superseded_by", weight=1.0)

    def _page_source_run_id(self, page: dict[str, Any]) -> str | None:
        source_candidate_id = page.get("source_candidate_id")
        if not source_candidate_id:
            return None
        source_candidate = self._get_candidate(str(source_candidate_id))
        return source_candidate.get("run_id") if source_candidate else None

    def _create_harmful_eval_case(
        self,
        memory_id: str,
        target_type: str,
        reason_text: str,
        *,
        status: str,
        tombstone_id: str,
        summary: str,
        eval_run_id: str | None,
        source_run_id: str | None,
        replacement: dict[str, Any] | None,
        dimension: Any = None,
        scope: Any = None,
    ) -> dict[str, Any] | None:
        if not _is_harmful_reason(reason_text):
            return None
        add_eval_case = getattr(self.store, "add_eval_case", None)
        if not add_eval_case:
            return None
        run_id = self._resolve_eval_run_id(eval_run_id, fallback=source_run_id)
        if not run_id:
            return None
        case = _harmful_memory_eval_case(
            memory_id,
            target_type,
            reason_text,
            status=status,
            tombstone_id=tombstone_id,
            summary=summary,
            source_run_id=source_run_id,
            dimension=dimension,
            scope=scope,
            replacement=replacement,
        )
        case_id = add_eval_case(
            run_id,
            f"memory harmful regression: {target_type}:{memory_id}",
            case,
        )
        get_eval_case = getattr(self.store, "get_eval_case", None)
        return _compact_eval_case(get_eval_case(case_id) if get_eval_case else None, case_id=case_id, run_id=run_id)

    def _resolve_eval_run_id(self, eval_run_id: str | None, *, fallback: str | None) -> str | None:
        explicit_run_id = _normalize_space(str(eval_run_id or ""))
        fallback_run_id = _normalize_space(str(fallback or ""))
        run_id = explicit_run_id or fallback_run_id
        if not run_id:
            return None
        get_run = getattr(self.store, "get_run", None)
        if get_run and not get_run(run_id):
            if not explicit_run_id:
                return None
            raise ValueError(f"Eval run not found for harmful memory tombstone: {run_id}")
        return run_id

    def _private_delete_page(
        self,
        page: dict[str, Any],
        reason_text: str,
        *,
        redact_source_candidate: bool,
    ) -> dict[str, Any]:
        page_id = str(page["id"])
        status = f"private_delete:{_status_reason(reason_text)}"
        target_hash = _memory_hash("page", page.get("title"), page.get("content"))
        source_candidate_id = page.get("source_candidate_id")
        source_candidate = self._get_candidate(str(source_candidate_id)) if source_candidate_id else None
        evidence_run_id = source_candidate.get("run_id") if source_candidate else None
        tombstone_id = self.store.add_memory_tombstone(
            page_id,
            "page",
            PRIVATE_DELETE_TOMBSTONE_REASON,
            summary=PRIVATE_DELETE_SUMMARY,
            target_hash=target_hash,
            evidence_run_id=evidence_run_id,
            rule=PRIVATE_DELETE_RULE,
            metadata=_private_delete_metadata(
                reason_text,
                previous_status=page.get("status"),
                target_hash=target_hash,
                scope=page.get("scope"),
            ),
        )
        redact_page = getattr(self.store, "redact_memory_page", None)
        if not redact_page:
            raise ValueError("memory page private delete is not supported by this store")
        redact_page(
            page_id,
            title=PRIVATE_DELETE_SUMMARY,
            content=PRIVATE_DELETE_SUMMARY,
            confidence=0.0,
            status=status,
            metadata=_private_delete_metadata(
                reason_text,
                previous_status=page.get("status"),
                target_hash=target_hash,
                scope=page.get("scope"),
            ),
        )

        related_redactions: list[dict[str, Any]] = []
        if redact_source_candidate and source_candidate and not _is_private_delete_status(source_candidate.get("status")):
            related_redactions.append(
                self._private_delete_candidate(
                    source_candidate,
                    reason_text,
                    redact_promoted_pages=False,
                )
            )
        updated_page = self._get_page(page_id)
        wiki = materialize_memory_page(self.store.state_dir, updated_page) if updated_page else None

        return {
            "kind": "memory_private_delete",
            "memory_id": page_id,
            "target_type": "page",
            "status": status,
            "reason": reason_text,
            "tombstone_reason": PRIVATE_DELETE_TOMBSTONE_REASON,
            "tombstone_id": tombstone_id,
            "target_hash": target_hash,
            "redacted": True,
            "memory": updated_page,
            "wiki": wiki,
            "related_redactions": _compact_private_redactions(related_redactions),
        }

    def _private_delete_candidate(
        self,
        candidate: dict[str, Any],
        reason_text: str,
        *,
        redact_promoted_pages: bool,
    ) -> dict[str, Any]:
        candidate_id = str(candidate["id"])
        status = f"private_delete:{_status_reason(reason_text)}"
        target_hash = _memory_hash("candidate", candidate.get("claim"), candidate.get("evidence"))
        tombstone_id = self.store.add_memory_tombstone(
            candidate_id,
            "candidate",
            PRIVATE_DELETE_TOMBSTONE_REASON,
            summary=PRIVATE_DELETE_SUMMARY,
            target_hash=target_hash,
            evidence_run_id=candidate.get("run_id"),
            rule=PRIVATE_DELETE_RULE,
            metadata=_private_delete_metadata(
                reason_text,
                previous_status=candidate.get("status"),
                target_hash=target_hash,
                dimension=candidate.get("dimension"),
                scope=candidate.get("scope"),
            ),
        )
        redact_candidate = getattr(self.store, "redact_memory_candidate", None)
        if not redact_candidate:
            raise ValueError("memory candidate private delete is not supported by this store")
        redact_candidate(
            candidate_id,
            claim=PRIVATE_DELETE_SUMMARY,
            confidence=0.0,
            status=status,
            evidence=[
                {
                    "kind": "private_delete",
                    "redacted": True,
                    "reason": reason_text,
                    "target_hash": target_hash,
                }
            ],
        )

        related_redactions: list[dict[str, Any]] = []
        if redact_promoted_pages:
            for page_id in self._promoted_page_ids(candidate_id):
                page = self._get_page(page_id)
                if not page or _is_private_delete_status(page.get("status")):
                    continue
                related_redactions.append(
                    self._private_delete_page(
                        page,
                        reason_text,
                        redact_source_candidate=False,
                    )
                )

        return {
            "kind": "memory_private_delete",
            "memory_id": candidate_id,
            "target_type": "candidate",
            "status": status,
            "reason": reason_text,
            "tombstone_reason": PRIVATE_DELETE_TOMBSTONE_REASON,
            "tombstone_id": tombstone_id,
            "target_hash": target_hash,
            "redacted": True,
            "memory": self._get_candidate(candidate_id),
            "related_redactions": _compact_private_redactions(related_redactions),
        }


def _memory_hash(kind: str, *parts: Any) -> str:
    payload = dumps(
        {
            "kind": kind,
            "parts": [part for part in parts if part is not None],
        }
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _add_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = int(target.get(key, 0)) + int(value)


def _resolved_target_type(pages: dict[str, dict[str, Any]], candidates: dict[str, dict[str, Any]]) -> str:
    if pages and not candidates:
        return "page"
    if candidates and not pages:
        return "candidate"
    if pages and candidates:
        return "mixed"
    return "missing"


def _private_delete_metadata(reason: str, **values: Any) -> dict[str, Any]:
    metadata = {
        "redaction": PRIVATE_DELETE_TOMBSTONE_REASON,
        "delete_reason": _truncate(reason, limit=120),
        "redacted_at": time.time(),
    }
    for key, value in values.items():
        if value is not None:
            metadata[key] = value
    return metadata

def _compact_private_redactions(redactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "memory_id": item.get("memory_id"),
            "target_type": item.get("target_type"),
            "status": item.get("status"),
            "tombstone_id": item.get("tombstone_id"),
            "redacted": bool(item.get("redacted")),
        }
        for item in redactions
    ]

def _harmful_memory_eval_case(
    memory_id: str,
    target_type: str,
    reason: str,
    *,
    status: str,
    tombstone_id: str,
    summary: str,
    source_run_id: str | None,
    dimension: Any,
    scope: Any,
    replacement: dict[str, Any] | None,
) -> dict[str, Any]:
    case = {
        "kind": "memory_harmful_regression",
        "suite": "memory-core",
        "memory_id": memory_id,
        "target_type": target_type,
        "tombstone_id": tombstone_id,
        "reason": _normalize_space(reason) or "harmful",
        "status": status,
        "summary": _truncate(summary, limit=178),
        "source_run_id": source_run_id,
        "expected": {
            "active_recall_excludes_target": True,
            "tombstone_respected": True,
            "do_not_resurrect_without_user_restatement": True,
        },
    }
    if dimension:
        case["dimension"] = dimension
    if scope:
        case["scope"] = scope
    if replacement:
        case["replacement_id"] = replacement.get("id")
        case["replacement_type"] = replacement.get("target_type")
    return case

def _compact_eval_case(
    eval_case: dict[str, Any] | None,
    *,
    case_id: str,
    run_id: str,
) -> dict[str, Any]:
    payload = eval_case.get("case") if isinstance(eval_case, dict) else {}
    return {
        "id": eval_case.get("id") if isinstance(eval_case, dict) else case_id,
        "run_id": eval_case.get("run_id") if isinstance(eval_case, dict) else run_id,
        "name": eval_case.get("name") if isinstance(eval_case, dict) else "memory harmful regression",
        "status": eval_case.get("status") if isinstance(eval_case, dict) else "draft",
        "kind": payload.get("kind") if isinstance(payload, dict) else "memory_harmful_regression",
        "suite": payload.get("suite") if isinstance(payload, dict) else "memory-core",
    }

def _curation_metadata(
    *,
    replacement: dict[str, Any] | None,
    replacement_link_id: str | None,
    **values: Any,
) -> dict[str, Any]:
    metadata = {key: value for key, value in values.items() if value is not None}
    if replacement:
        metadata["replacement_id"] = replacement["id"]
        metadata["replacement_type"] = replacement["target_type"]
        if replacement_link_id:
            metadata["replacement_link_id"] = replacement_link_id
    return metadata
