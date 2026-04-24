from __future__ import annotations

import re
from typing import Any


class MemoryEngine:
    def __init__(self, store: Any):
        self.store = store

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        normalized_query = query.strip()
        if not normalized_query:
            return []

        page_limit = max(limit, 1)
        candidate_limit = max(limit, 1)
        pages = self.store.search_memory_pages(normalized_query, limit=page_limit)
        candidates = self.store.search_memory_candidates(normalized_query, limit=candidate_limit)

        results: list[dict[str, Any]] = []
        for page in pages:
            results.append(
                {
                    "type": "page",
                    "id": page["id"],
                    "title": page["title"],
                    "content": page["content"],
                    "scope": page["scope"],
                    "confidence": page["confidence"],
                    "status": page["status"],
                    "source_candidate_id": page.get("source_candidate_id"),
                }
            )
        for candidate in candidates:
            results.append(
                {
                    "type": "candidate",
                    "id": candidate["id"],
                    "claim": candidate["claim"],
                    "dimension": candidate.get("dimension"),
                    "scope": candidate["scope"],
                    "confidence": candidate["confidence"],
                    "status": candidate["status"],
                    "evidence": candidate.get("evidence", []),
                }
            )
        return results

    def context_cards(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return [_context_card(item) for item in self.search(query, limit=limit)]

    def promote_candidate(self, candidate_id: str) -> dict[str, Any]:
        candidate = self._get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Memory candidate not found: {candidate_id}")

        claim = _normalize_space(candidate.get("claim", ""))
        if not claim:
            raise ValueError(f"Memory candidate is empty: {candidate_id}")

        page_id = self.store.upsert_memory_page(
            _candidate_title(candidate),
            claim,
            scope=candidate.get("scope") or "global",
            source_candidate_id=candidate_id,
            confidence=float(candidate.get("confidence", 0.7)),
        )
        self.store.update_memory_candidate_status(candidate_id, "promoted")
        self.store.add_memory_link(candidate_id, page_id, "promoted_to", weight=1.0)
        page = self._get_page(page_id)
        return {
            "candidate_id": candidate_id,
            "page_id": page_id,
            "status": "promoted",
            "page": page,
        }

    def reject_candidate(self, candidate_id: str, reason: str) -> dict[str, Any]:
        candidate = self._get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Memory candidate not found: {candidate_id}")

        status = f"rejected:{_status_reason(reason)}"
        self.store.update_memory_candidate_status(candidate_id, status)
        return {
            "candidate_id": candidate_id,
            "status": status,
            "reason": reason,
        }

    def dream_consolidate(self, limit: int = 20, min_confidence: float = 0.7) -> dict[str, Any]:
        candidates = self.store.list_memory_candidates(status="draft", limit=limit)
        promoted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        seen_claims: set[str] = set()

        for candidate in sorted(
            candidates,
            key=lambda item: (item.get("created_at", 0), item["id"]),
        ):
            claim = _normalize_space(candidate.get("claim", ""))
            fingerprint = _fingerprint(claim)

            if not claim:
                rejected.append(self.reject_candidate(candidate["id"], "empty"))
                continue

            if fingerprint in seen_claims or self._has_duplicate_page(claim):
                rejected.append(self.reject_candidate(candidate["id"], "duplicate"))
                continue

            seen_claims.add(fingerprint)
            confidence = float(candidate.get("confidence", 0.0))
            if confidence >= min_confidence:
                promoted.append(self.promote_candidate(candidate["id"]))
            else:
                skipped.append(
                    {
                        "candidate_id": candidate["id"],
                        "status": candidate.get("status", "draft"),
                        "reason": "below_confidence_threshold",
                    }
                )

        return {
            "promoted": promoted,
            "rejected": rejected,
            "skipped": skipped,
        }

    def _get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        get_candidate = getattr(self.store, "get_memory_candidate", None)
        if get_candidate:
            return get_candidate(candidate_id)

        candidates = self.store.list_memory_candidates(status=None, limit=1000)
        return next((candidate for candidate in candidates if candidate["id"] == candidate_id), None)

    def _get_page(self, page_id: str) -> dict[str, Any] | None:
        get_page = getattr(self.store, "get_memory_page", None)
        if get_page:
            return get_page(page_id)
        return None

    def _has_duplicate_page(self, claim: str) -> bool:
        matches = self.store.search_memory_pages(claim, limit=1)
        return any(
            _fingerprint(page.get("content", "")) == _fingerprint(claim)
            for page in matches
        )


def _candidate_title(candidate: dict[str, Any]) -> str:
    claim = _normalize_space(candidate.get("claim", ""))
    dimension = candidate.get("dimension") or "memory"
    title_body = claim[:72].rstrip()
    return f"{dimension}: {title_body}"


def _context_card(item: dict[str, Any]) -> dict[str, Any]:
    if item["type"] == "page":
        return {
            "id": item["id"],
            "type": "page",
            "title": item["title"],
            "summary": _truncate(item["content"]),
            "confidence": item.get("confidence"),
            "status": item.get("status"),
        }
    return {
        "id": item["id"],
        "type": "candidate",
        "title": item.get("dimension") or "memory candidate",
        "summary": _truncate(item["claim"]),
        "confidence": item.get("confidence"),
        "status": item.get("status"),
    }


def _fingerprint(value: str) -> str:
    return re.sub(r"\W+", "", value.casefold())


def _normalize_space(value: str) -> str:
    return " ".join(value.strip().split())


def _truncate(value: str, limit: int = 220) -> str:
    compact = _normalize_space(value)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _status_reason(reason: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", reason.casefold()).strip("_")
    return normalized or "unspecified"
