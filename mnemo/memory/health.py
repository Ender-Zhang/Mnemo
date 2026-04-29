from __future__ import annotations

import time
from typing import Any

from .associations import has_metadata_associations
from .query import MEMORY_DIMENSION_ALIASES, MEMORY_ONTOLOGY_DIMENSIONS, normalize_memory_dimension
from .utils import (
    _bounded_confidence,
    _is_stale_status,
    _is_tombstone_status,
    _metadata_timestamp,
    _non_negative_float,
    _truncate,
)
from .wiki import materialize_memory_page


class MemoryHealthMixin:
    def health_report(self, limit: int = 20) -> dict[str, Any]:
        card_limit = max(1, min(50, int(limit)))
        inventory_limit = max(50, card_limit * 5)
        pages = self.store.list_memory_pages(status=None, limit=inventory_limit)
        candidates = self.store.list_memory_candidates(status=None, limit=inventory_limit)
        list_tombstones = getattr(self.store, "list_memory_tombstones", None)
        tombstones = list_tombstones(limit=inventory_limit) if list_tombstones else []
        active_pages = [page for page in pages if page.get("status") == "active"]
        stale_pages = [page for page in pages if _is_stale_status(page.get("status"))]
        tombstoned_pages = [page for page in pages if _is_tombstone_status(page.get("status"))]
        draft_candidates = [item for item in candidates if item.get("status") == "draft"]
        review_candidates = [item for item in candidates if str(item.get("status") or "").startswith("needs_review")]
        rejected_candidates = [item for item in candidates if _is_tombstone_status(item.get("status"))]
        orphan_pages = [page for page in active_pages if self._is_orphan_page(page["id"])]
        low_confidence_pages = [
            page
            for page in active_pages
            if float(page.get("confidence") or 0.0) < 0.65
        ]
        now = time.time()
        decay_due = [
            (page, decision)
            for page in active_pages
            for decision in [_page_decay_decision(page, now=now, stale_confidence=0.35)]
            if decision["action"] != "skip"
        ]
        expired_pages = [
            page
            for page, decision in decay_due
            if "expired" in decision.get("reasons", [])
        ]
        dimensions = _dimension_counts(active_pages, candidates)
        review_cards = _bounded_cards(
            [
                *[
                    _page_review_card("verify_stale", page)
                    for page, _decision in decay_due
                ],
                *[_page_review_card("verify_stale", page) for page in stale_pages],
                *[_page_review_card("improve_evidence", page) for page in low_confidence_pages],
                *[
                    _candidate_review_card(_candidate_review_kind(candidate), candidate)
                    for candidate in review_candidates
                ],
                *[_tombstone_review_card(tombstone) for tombstone in tombstones[:card_limit]],
                *[_page_review_card("connect_orphan", page) for page in orphan_pages],
            ],
            limit=card_limit,
        )
        return {
            "kind": "memory_health_report",
            "generated_at": time.time(),
            "counts": {
                "pages": {
                    "total": len(pages),
                    "active": len(active_pages),
                    "stale": len(stale_pages),
                    "tombstoned": len(tombstoned_pages),
                    "orphan_active": len(orphan_pages),
                    "low_confidence_active": len(low_confidence_pages),
                    "decay_due_active": len(decay_due),
                    "expired_active": len(expired_pages),
                },
                "candidates": {
                    "total": len(candidates),
                    "draft": len(draft_candidates),
                    "needs_review": len(review_candidates),
                    "rejected_or_tombstoned": len(rejected_candidates),
                },
                "tombstones": len(tombstones),
            },
            "coverage": {
                "dimensions": dimensions,
                "covered": sum(1 for count in dimensions.values() if count > 0),
                "total": len(dimensions),
            },
            "score": _health_score(
                dimensions=dimensions,
                active_pages=active_pages,
                stale_pages=stale_pages,
                orphan_pages=orphan_pages,
                low_confidence_pages=low_confidence_pages,
                review_candidates=review_candidates,
            ),
            "review_cards": review_cards,
        }

    def decay_stale_pages(
        self,
        limit: int = 50,
        *,
        now: float | None = None,
        stale_confidence: float = 0.35,
    ) -> dict[str, Any]:
        generated_at = time.time() if now is None else float(now)
        bounded_limit = max(0, min(200, int(limit)))
        threshold = _bounded_confidence(stale_confidence, 0.35)
        pages = self.store.list_memory_pages(status="active", limit=bounded_limit)
        decayed: list[dict[str, Any]] = []
        staled: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        review_cards: list[dict[str, Any]] = []

        for page in pages:
            decision = _page_decay_decision(page, now=generated_at, stale_confidence=threshold)
            if decision["action"] == "skip":
                skipped.append({"page_id": page.get("id"), "reason": decision["reason"]})
                continue

            page_id = str(page["id"])
            changed = False
            if decision.get("decayed"):
                self.store.update_memory_page_confidence(page_id, decision["confidence"])
                decayed.append(_compact_decay_change(page, decision))
                changed = True

            if decision.get("stale"):
                self.store.update_memory_page_status(page_id, decision["status"])
                stale_item = _compact_decay_change(page, decision)
                stale_item["status"] = decision["status"]
                staled.append(stale_item)
                updated_page = self._get_page(page_id) or {**page, "status": decision["status"]}
                review_cards.append(_page_review_card("verify_stale", updated_page))
                materialize_memory_page(self.store.state_dir, updated_page)
                changed = False

            if changed:
                updated_page = self._get_page(page_id) or page
                materialize_memory_page(self.store.state_dir, updated_page)

        return {
            "kind": "memory_decay_report",
            "generated_at": generated_at,
            "limit": bounded_limit,
            "stale_confidence": threshold,
            "counts": {
                "checked": len(pages),
                "decayed": len(decayed),
                "staled": len(staled),
                "skipped": len(skipped),
            },
            "decayed": decayed,
            "staled": staled,
            "skipped": skipped[: min(20, bounded_limit)],
            "review_cards": _bounded_cards(review_cards, limit=min(20, bounded_limit)),
        }

    def _is_orphan_page(self, page_id: str) -> bool:
        list_links = getattr(self.store, "list_memory_links", None)
        if list_links and list_links(page_id):
            return False
        list_backlinks = getattr(self.store, "list_memory_backlinks", None)
        if list_backlinks and list_backlinks(page_id):
            return False
        if has_metadata_associations(self.store, page_id):
            return False
        return True


def _dimension_counts(pages: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts = {dimension: 0 for dimension in MEMORY_ONTOLOGY_DIMENSIONS}
    for page in pages:
        dimension = _infer_dimension(page.get("title") or page.get("scope") or "")
        if dimension in counts:
            counts[dimension] += 1
    for candidate in candidates:
        if candidate.get("status") not in {"draft", "needs_review:conflict"}:
            continue
        dimension = _infer_dimension(candidate.get("dimension") or candidate.get("scope") or "")
        if dimension in counts:
            counts[dimension] += 1
    return counts

def _infer_dimension(value: str) -> str:
    text = str(value or "").strip().casefold()
    head = text.split(":", 1)[0].strip()
    if head in MEMORY_ONTOLOGY_DIMENSIONS or head in MEMORY_DIMENSION_ALIASES:
        return normalize_memory_dimension(head, fallback="context")
    for dimension in MEMORY_ONTOLOGY_DIMENSIONS:
        if dimension in text:
            return dimension
    return "context"

def _bounded_cards(cards: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return cards[: max(0, int(limit))]

def _page_review_card(kind: str, page: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "target_type": "page",
        "target_id": page.get("id"),
        "title": _truncate(page.get("title", ""), limit=96),
        "summary": _truncate(page.get("content", ""), limit=180),
        "status": page.get("status"),
        "confidence": page.get("confidence"),
        "updated_at": page.get("updated_at"),
        "actions": _review_actions(kind),
    }

def _page_decay_decision(page: dict[str, Any], *, now: float, stale_confidence: float) -> dict[str, Any]:
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    expires_value = metadata["expires_at"] if "expires_at" in metadata else metadata.get("expires")
    expires_at = _metadata_timestamp(expires_value)
    decay_days = _non_negative_float(metadata.get("decay_days"))
    current_confidence = _bounded_confidence(page.get("confidence"), 0.0)
    base_at = _memory_page_decay_base_at(page, metadata, now=now)
    age_days = max(0.0, (now - base_at) / 86400.0)
    reasons: list[str] = []

    expired = expires_at is not None and expires_at <= now
    if expired:
        reasons.append("expired")

    confidence = current_confidence
    overdue_days = 0.0
    decayed = False
    if decay_days is not None and age_days > decay_days:
        overdue_days = age_days - decay_days
        confidence = max(0.0, current_confidence - (0.01 * overdue_days))
        decayed = confidence < current_confidence
        if decayed:
            reasons.append("decay_due")

    stale = expired or confidence <= stale_confidence
    if stale and not expired and "decay_due" in reasons:
        reasons.append("low_confidence")

    if not reasons:
        reason = "no_decay_metadata" if expires_at is None and decay_days is None else "not_due"
        return {
            "action": "skip",
            "reason": reason,
            "confidence": round(confidence, 6),
            "previous_confidence": round(current_confidence, 6),
            "age_days": round(age_days, 3),
        }

    status = "stale:expired" if expired else "stale:decay"
    return {
        "action": "stale" if stale else "decay",
        "status": status if stale else None,
        "stale": stale,
        "decayed": decayed,
        "reasons": reasons,
        "confidence": round(confidence, 6),
        "previous_confidence": round(current_confidence, 6),
        "age_days": round(age_days, 3),
        "decay_days": decay_days,
        "overdue_days": round(overdue_days, 3),
        "expires_at": expires_at,
    }

def _compact_decay_change(page: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_id": page.get("id"),
        "title": _truncate(page.get("title", ""), limit=96),
        "scope": page.get("scope") or "global",
        "reasons": decision.get("reasons", []),
        "previous_confidence": decision.get("previous_confidence"),
        "confidence": decision.get("confidence"),
        "age_days": decision.get("age_days"),
        "decay_days": decision.get("decay_days"),
        "overdue_days": decision.get("overdue_days"),
        "expires_at": decision.get("expires_at"),
    }

def _memory_page_decay_base_at(page: dict[str, Any], metadata: dict[str, Any], *, now: float) -> float:
    for value in (
        metadata.get("last_verified_at"),
        metadata.get("verified_at"),
        page.get("updated_at"),
        page.get("created_at"),
    ):
        parsed = _metadata_timestamp(value)
        if parsed is not None:
            return parsed
    return now

def _candidate_review_card(kind: str, candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "target_type": "candidate",
        "target_id": candidate.get("id"),
        "title": candidate.get("dimension") or "memory candidate",
        "summary": _truncate(candidate.get("claim", ""), limit=180),
        "status": candidate.get("status"),
        "confidence": candidate.get("confidence"),
        "created_at": candidate.get("created_at"),
        "actions": _review_actions(kind),
    }

def _candidate_review_kind(candidate: dict[str, Any]) -> str:
    status = str(candidate.get("status") or "")
    if "prompt_injection" in status or "memory_safety" in status:
        return "review_memory_safety"
    return "review_conflict"

def _tombstone_review_card(tombstone: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "respect_tombstone",
        "target_type": tombstone.get("target_type"),
        "target_id": tombstone.get("target_id"),
        "tombstone_id": tombstone.get("id"),
        "title": f"Do not resurrect: {tombstone.get('reason')}",
        "summary": _truncate(tombstone.get("summary", ""), limit=180),
        "reason": tombstone.get("reason"),
        "created_at": tombstone.get("created_at"),
        "actions": ["avoid_relearning"],
    }

def _review_actions(kind: str) -> list[str]:
    if kind == "verify_stale":
        return ["confirm", "archive", "tombstone"]
    if kind == "review_conflict":
        return ["promote", "reject", "tombstone"]
    if kind == "review_memory_safety":
        return ["reject", "tombstone", "manual_review"]
    if kind == "connect_orphan":
        return ["link", "leave"]
    if kind == "improve_evidence":
        return ["verify", "leave"]
    return ["review"]

def _health_score(
    *,
    dimensions: dict[str, int],
    active_pages: list[dict[str, Any]],
    stale_pages: list[dict[str, Any]],
    orphan_pages: list[dict[str, Any]],
    low_confidence_pages: list[dict[str, Any]],
    review_candidates: list[dict[str, Any]],
) -> dict[str, float]:
    total_dimensions = max(1, len(dimensions))
    active_count = max(1, len(active_pages))
    coverage = sum(1 for count in dimensions.values() if count > 0) / total_dimensions
    freshness = 1.0 - min(1.0, len(stale_pages) / max(1, len(active_pages) + len(stale_pages)))
    connectedness = 1.0 - min(1.0, len(orphan_pages) / active_count)
    evidence_quality = 1.0 - min(1.0, len(low_confidence_pages) / active_count)
    safety = 1.0 - min(1.0, len(review_candidates) / max(1, len(review_candidates) + active_count))
    return {
        "coverage": round(coverage, 3),
        "freshness": round(freshness, 3),
        "connectedness": round(connectedness, 3),
        "evidence_quality": round(evidence_quality, 3),
        "safety": round(safety, 3),
        "overall": round((coverage + freshness + connectedness + evidence_quality + safety) / 5, 3),
    }
