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
        conflicts: list[dict[str, Any]] = []
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

            duplicate_page = self._find_duplicate_page(claim)
            if fingerprint in seen_claims or duplicate_page:
                if duplicate_page:
                    self._reinforce_page(candidate, duplicate_page)
                rejected.append(self.reject_candidate(candidate["id"], "duplicate"))
                continue

            seen_claims.add(fingerprint)
            confidence = float(candidate.get("confidence", 0.0))
            conflict_page = self._find_conflicting_page(candidate)
            if conflict_page:
                conflicts.append(self._mark_conflict(candidate, conflict_page))
                continue

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
            "conflicts": conflicts,
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

    def _find_duplicate_page(self, claim: str) -> dict[str, Any] | None:
        matches = self.store.search_memory_pages(claim, limit=1)
        return next(
            (
                page
                for page in matches
                if _fingerprint(page.get("content", "")) == _fingerprint(claim)
            ),
            None,
        )

    def _reinforce_page(self, candidate: dict[str, Any], page: dict[str, Any]) -> None:
        page_confidence = float(page.get("confidence", 0.0))
        candidate_confidence = float(candidate.get("confidence", 0.0))
        confidence = min(1.0, max(page_confidence, candidate_confidence) + 0.05)
        update_confidence = getattr(self.store, "update_memory_page_confidence", None)
        if update_confidence:
            update_confidence(page["id"], confidence)
        self.store.add_memory_link(candidate["id"], page["id"], "reinforces", weight=confidence)

    def _find_conflicting_page(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        claim = _normalize_space(candidate.get("claim", ""))
        if not claim:
            return None
        polarity = _polarity(claim)
        if polarity == "neutral":
            return None
        queries = [
            candidate.get("dimension") or "",
            *_keywords(claim)[:4],
        ]
        seen: set[str] = set()
        for query in queries:
            if not query:
                continue
            for page in self.store.search_memory_pages(str(query), limit=10):
                page_id = str(page.get("id"))
                if page_id in seen:
                    continue
                seen.add(page_id)
                if _is_conflict(claim, page.get("content", "")):
                    return page
        return None

    def _mark_conflict(self, candidate: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
        status = "needs_review:conflict"
        self.store.update_memory_candidate_status(candidate["id"], status)
        self.store.add_memory_link(candidate["id"], page["id"], "conflicts_with", weight=float(candidate.get("confidence", 0.5)))
        return {
            "candidate_id": candidate["id"],
            "status": status,
            "conflict_page_id": page["id"],
            "reason": "conflicts_with_active_memory",
        }


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


def _keywords(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    return [
        token
        for token in tokens
        if len(token) > 2 and token not in _STOPWORDS
    ]


def _polarity(value: str) -> str:
    text = f" {_normalize_space(value).casefold()} "
    if any(marker in text for marker in _NEGATIVE_MARKERS):
        return "negative"
    if any(marker in text for marker in _POSITIVE_MARKERS):
        return "positive"
    return "neutral"


def _is_conflict(left: str, right: str) -> bool:
    left_polarity = _polarity(left)
    right_polarity = _polarity(right)
    if {left_polarity, right_polarity} != {"positive", "negative"}:
        return False
    left_keywords = set(_keywords(left))
    right_keywords = set(_keywords(right))
    return bool(left_keywords & right_keywords)


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


_POSITIVE_MARKERS = (
    " prefer ",
    " prefers ",
    " like ",
    " likes ",
    " want ",
    " wants ",
    " use ",
    " uses ",
)
_NEGATIVE_MARKERS = (
    " dislike ",
    " dislikes ",
    " avoid ",
    " avoids ",
    " do not ",
    " does not ",
    " don't ",
    " never ",
    " hate ",
    " hates ",
)
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "user",
    "prefers",
    "prefer",
    "likes",
    "like",
    "dislikes",
    "dislike",
    "wants",
    "want",
    "uses",
    "use",
    "does",
    "not",
    "dont",
    "never",
}
