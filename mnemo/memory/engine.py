from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from ..core.jsonutil import dumps, loads
from .query import CONTENT_DIMENSIONS, MemoryQueryPlan, annotate_memory_match, build_memory_query_plan, fuse_ranked_batches
from .safety import append_safety_evidence, scan_memory_candidate

L1_SNAPSHOT_FILENAME = "l1-memory-snapshot.json"
W0_MEMORY_RETENTION = "memory_candidate"
DEFAULT_W0_CONFIDENCE = 0.62
MIN_W0_CANDIDATE_CHARS = 12
MEMORY_SEARCH_SCOPES = {"memory", "stable", "sessions", "all"}


class MemoryEngine:
    def __init__(self, store: Any):
        self.store = store

    def plan_query(self, query: str) -> MemoryQueryPlan:
        return build_memory_query_plan(query, l1_snapshot=self.load_l1_snapshot())

    def search_with_plan(self, query: str, limit: int = 5, *, search_scope: str = "memory") -> dict[str, Any]:
        plan = self.plan_query(query)
        if not plan.original:
            return {"query_plan": plan.metadata(), "matches": []}
        return {
            "query_plan": plan.metadata(),
            "matches": self._search_from_plan(plan, limit=limit, search_scope=search_scope),
        }

    def search(self, query: str, limit: int = 5, *, search_scope: str = "memory") -> list[dict[str, Any]]:
        return self.search_with_plan(query, limit=limit, search_scope=search_scope)["matches"]

    def _search_from_plan(
        self,
        plan: MemoryQueryPlan,
        *,
        limit: int,
        search_scope: str,
    ) -> list[dict[str, Any]]:
        normalized_scope = _normalize_search_scope(search_scope)
        bounded_limit = max(1, int(limit))

        results: list[dict[str, Any]] = []
        if normalized_scope in {"memory", "all"}:
            memory_results = self._search_memory_routes(plan, limit=bounded_limit)
            results.extend(memory_results)
            page_seeds = [item for item in memory_results if item["type"] == "page"]
            results.extend(
                self._associated_pages(
                    page_seeds,
                    seen_ids={item["id"] for item in results},
                    limit=bounded_limit,
                    plan=plan,
                )
            )

        if normalized_scope in {"sessions", "all"}:
            results.extend(self._search_session_routes(plan, limit=bounded_limit))
        return results

    def _search_memory_routes(self, plan: MemoryQueryPlan, *, limit: int) -> list[dict[str, Any]]:
        batches: list[tuple[str, str, list[dict[str, Any]]]] = []
        for route in plan.routes():
            query = route["query"]
            pages = [
                _page_result(page)
                for page in self.store.search_memory_pages(query, limit=max(limit, 1))
            ]
            candidates = [
                _candidate_result(candidate)
                for candidate in self.store.search_memory_candidates(query, limit=max(limit, 1))
            ]
            batches.append((route["route"], query, [*pages, *candidates]))
        return fuse_ranked_batches(batches, plan=plan, limit=max(limit * 2, 1))

    def _search_session_routes(self, plan: MemoryQueryPlan, *, limit: int) -> list[dict[str, Any]]:
        search_session_messages = getattr(self.store, "search_session_messages", None)
        if not search_session_messages:
            return []
        batches: list[tuple[str, str, list[dict[str, Any]]]] = []
        for route in plan.routes():
            messages = [
                _session_result(message)
                for message in search_session_messages(route["query"], limit=max(limit, 1))
            ]
            batches.append((route["route"], route["query"], messages))
        return fuse_ranked_batches(batches, plan=plan, limit=max(limit, 1))

    def context_cards(self, query: str, limit: int = 5, *, search_scope: str = "memory") -> list[dict[str, Any]]:
        return [_context_card(item) for item in self.search(query, limit=limit, search_scope=search_scope)]

    def write_candidate(
        self,
        run_id: str,
        claim: str,
        *,
        dimension: str | None = None,
        scope: str = "global",
        confidence: float = 0.5,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        scan = scan_memory_candidate(claim, evidence)
        candidate_id = self.store.add_memory_candidate(
            run_id,
            claim,
            dimension=dimension,
            scope=scope,
            confidence=confidence,
            evidence=append_safety_evidence(evidence, scan),
        )
        status = "draft"
        if scan.get("requires_review"):
            status = f"needs_review:{scan.get('review_reason') or 'memory_safety'}"
            self.store.update_memory_candidate_status(candidate_id, status)
        return {
            "candidate_id": candidate_id,
            "status": status,
            "safety": _compact_safety_scan(scan),
        }

    def ingest_working_notes(self, limit: int = 20) -> dict[str, Any]:
        list_notes = getattr(self.store, "list_working_notes", None)
        update_note = getattr(self.store, "update_working_note_status", None)
        if not list_notes or not update_note:
            return {"created": [], "skipped": []}

        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for note in list_notes(status="open", limit=limit):
            content = _normalize_space(note.get("content", ""))
            metadata = note.get("metadata") if isinstance(note.get("metadata"), dict) else {}
            retention = metadata.get("retention") or "ephemeral"

            if len(content) < MIN_W0_CANDIDATE_CHARS:
                skipped.append(_skip_working_note(self.store, note, "too_short"))
                continue
            if retention != W0_MEMORY_RETENTION:
                skipped.append(_skip_working_note(self.store, note, "ephemeral"))
                continue

            candidate = self.write_candidate(
                note["run_id"],
                content,
                dimension=metadata.get("dimension") or "working_note",
                scope=metadata.get("scope") or f"mission:{note['mission_id']}",
                confidence=_bounded_confidence(metadata.get("confidence"), DEFAULT_W0_CONFIDENCE),
                evidence=[
                    {
                        "kind": "working_note",
                        "id": note["id"],
                        "mission_id": note["mission_id"],
                        "run_id": note["run_id"],
                    }
                ],
            )
            candidate_id = candidate["candidate_id"]
            result = {
                "note_id": note["id"],
                "candidate_id": candidate_id,
                "status": "candidate_created",
                "candidate_status": candidate["status"],
                "safety": candidate["safety"],
            }
            self.store.update_working_note_status(
                note["id"],
                "candidate_created",
                result={"candidate_id": candidate_id},
            )
            created.append(result)

        return {"created": created, "skipped": skipped}

    def compile_l1_snapshot(self, limit: int = 50) -> dict[str, Any]:
        pages = self.store.list_memory_pages(status="active", limit=max(0, int(limit)))
        items = [_snapshot_item(page) for page in pages]
        snapshot = {
            "kind": "l1_memory_snapshot",
            "generated_at": time.time(),
            "page_count": len(items),
            "items": items,
        }
        path = self._l1_snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(snapshot), encoding="utf-8")
        return snapshot

    def load_l1_snapshot(self) -> dict[str, Any] | None:
        path = self._l1_snapshot_path()
        try:
            snapshot = loads(path.read_text(encoding="utf-8"), {})
        except (OSError, TypeError, ValueError):
            return None
        if not isinstance(snapshot, dict):
            return None
        if snapshot.get("kind") != "l1_memory_snapshot":
            return None
        items = snapshot.get("items")
        if not isinstance(items, list):
            return None
        return snapshot

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

        reason_text = _normalize_space(reason) or "unspecified"
        status = f"rejected:{_status_reason(reason_text)}"
        self.store.update_memory_candidate_status(candidate_id, status)
        result = {
            "candidate_id": candidate_id,
            "status": status,
            "reason": reason_text,
        }
        add_tombstone = getattr(self.store, "add_memory_tombstone", None)
        if add_tombstone:
            result["tombstone_id"] = add_tombstone(
                candidate_id,
                "candidate",
                reason_text,
                summary=_truncate(candidate.get("claim", ""), limit=180),
                evidence_run_id=candidate.get("run_id"),
                metadata={
                    "status": status,
                    "dimension": candidate.get("dimension"),
                    "scope": candidate.get("scope"),
                },
            )
        return result

    def tombstone_memory(
        self,
        memory_id: str,
        reason: str,
        *,
        target_type: str = "auto",
    ) -> dict[str, Any]:
        normalized_target_type = _normalize_tombstone_target_type(target_type)
        reason_text = _normalize_space(reason) or "unspecified"
        reason_slug = _status_reason(reason_text)
        if normalized_target_type in {"auto", "page"}:
            page = self._get_page(memory_id)
            if page:
                status = f"tombstoned:{reason_slug}"
                update_page_status = getattr(self.store, "update_memory_page_status", None)
                if not update_page_status:
                    raise ValueError("memory page tombstone is not supported by this store")
                update_page_status(memory_id, status)
                tombstone_id = self.store.add_memory_tombstone(
                    memory_id,
                    "page",
                    reason_text,
                    summary=_truncate(page.get("content", ""), limit=180),
                    metadata={
                        "title": page.get("title"),
                        "scope": page.get("scope"),
                        "previous_status": page.get("status"),
                    },
                )
                return {
                    "memory_id": memory_id,
                    "target_type": "page",
                    "status": status,
                    "reason": reason_text,
                    "tombstone_id": tombstone_id,
                    "memory": self._get_page(memory_id),
                }

        if normalized_target_type in {"auto", "candidate"}:
            candidate = self._get_candidate(memory_id)
            if candidate:
                status = f"tombstoned:{reason_slug}"
                self.store.update_memory_candidate_status(memory_id, status)
                tombstone_id = self.store.add_memory_tombstone(
                    memory_id,
                    "candidate",
                    reason_text,
                    summary=_truncate(candidate.get("claim", ""), limit=180),
                    evidence_run_id=candidate.get("run_id"),
                    metadata={
                        "dimension": candidate.get("dimension"),
                        "scope": candidate.get("scope"),
                        "previous_status": candidate.get("status"),
                    },
                )
                return {
                    "memory_id": memory_id,
                    "target_type": "candidate",
                    "status": status,
                    "reason": reason_text,
                    "tombstone_id": tombstone_id,
                    "memory": self._get_candidate(memory_id),
                }

        raise ValueError(f"Memory item not found for tombstone: {memory_id}")

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
        dimensions = _dimension_counts(active_pages, candidates)
        review_cards = _bounded_cards(
            [
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

    def dream_consolidate(self, limit: int = 20, min_confidence: float = 0.7) -> dict[str, Any]:
        w0 = self.ingest_working_notes(limit=limit)
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
            "w0": w0,
            "promoted": promoted,
            "rejected": rejected,
            "skipped": skipped,
            "conflicts": conflicts,
            "snapshot": self.compile_l1_snapshot(limit=50),
        }

    def _l1_snapshot_path(self) -> Path:
        return self.store.state_dir / "wiki" / L1_SNAPSHOT_FILENAME

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

    def _associated_pages(
        self,
        pages: list[dict[str, Any]],
        *,
        seen_ids: set[str],
        limit: int,
        plan: MemoryQueryPlan,
    ) -> list[dict[str, Any]]:
        associated: list[dict[str, Any]] = []
        max_associations = max(0, int(limit))
        if not pages or max_associations == 0:
            return associated

        for page in pages:
            page_id = page["id"]
            for link, linked_page_id in self._page_association_links(page_id):
                if linked_page_id in seen_ids:
                    continue
                linked_page = self._get_page(linked_page_id)
                if not linked_page or linked_page.get("status") != "active":
                    continue
                associated.append(
                    annotate_memory_match(
                        {
                            "type": "linked_page",
                            "id": linked_page["id"],
                            "title": linked_page["title"],
                            "content": linked_page["content"],
                            "scope": linked_page["scope"],
                            "confidence": linked_page["confidence"],
                            "status": linked_page["status"],
                            "source_candidate_id": linked_page.get("source_candidate_id"),
                            "relation": link["relation"],
                            "linked_from": page_id,
                            "link_id": link["id"],
                            "link_weight": link["weight"],
                            "match_signals": [
                                {"route": "wiki", "query": page.get("title") or page_id, "rank": len(associated) + 1}
                            ],
                        },
                        plan,
                        score=float(link.get("weight", 0.0)),
                    )
                )
                seen_ids.add(linked_page_id)
                if len(associated) >= max_associations:
                    return associated
        return associated

    def _page_association_links(self, page_id: str) -> list[tuple[dict[str, Any], str]]:
        links: list[tuple[dict[str, Any], str]] = []
        list_links = getattr(self.store, "list_memory_links", None)
        if list_links:
            links.extend((link, link["target_id"]) for link in list_links(page_id))

        list_backlinks = getattr(self.store, "list_memory_backlinks", None)
        if list_backlinks:
            links.extend((link, link["source_id"]) for link in list_backlinks(page_id))

        return sorted(
            links,
            key=lambda item: (
                -float(item[0].get("weight", 0.0)),
                -float(item[0].get("created_at", 0.0)),
                item[0].get("id", ""),
            ),
        )

    def _is_orphan_page(self, page_id: str) -> bool:
        list_links = getattr(self.store, "list_memory_links", None)
        if list_links and list_links(page_id):
            return False
        list_backlinks = getattr(self.store, "list_memory_backlinks", None)
        if list_backlinks and list_backlinks(page_id):
            return False
        return True

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
        self.store.add_memory_link(
            candidate["id"],
            page["id"],
            "conflicts_with",
            weight=float(candidate.get("confidence", 0.5)),
        )
        return {
            "candidate_id": candidate["id"],
            "status": status,
            "conflict_page_id": page["id"],
            "reason": "conflicts_with_active_memory",
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
        "dimension": candidate.get("dimension"),
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


def _candidate_title(candidate: dict[str, Any]) -> str:
    claim = _normalize_space(candidate.get("claim", ""))
    dimension = candidate.get("dimension") or "memory"
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
    return {
        "id": item["id"],
        "type": "candidate",
        "title": item.get("dimension") or "memory candidate",
        "summary": _truncate(item["claim"]),
        "confidence": item.get("confidence"),
        "status": item.get("status"),
    }


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


def _bounded_confidence(value: Any, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return min(1.0, max(0.0, confidence))


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


def _normalize_search_scope(value: str) -> str:
    normalized = str(value or "memory").strip().casefold()
    if normalized not in MEMORY_SEARCH_SCOPES:
        raise ValueError(f"invalid memory search scope: {value}")
    if normalized == "stable":
        return "memory"
    return normalized


def _normalize_tombstone_target_type(value: str) -> str:
    normalized = str(value or "auto").strip().casefold()
    if normalized not in {"auto", "candidate", "page"}:
        raise ValueError(f"invalid memory tombstone target type: {value}")
    return normalized


def _compact_safety_scan(scan: dict[str, Any]) -> dict[str, Any]:
    return {
        "taint": scan.get("taint"),
        "risk": scan.get("risk"),
        "requires_review": bool(scan.get("requires_review")),
        "review_reason": scan.get("review_reason"),
        "sources": scan.get("sources", [])[:6],
        "warnings": scan.get("warnings", [])[:6],
    }


def _dimension_counts(pages: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts = {dimension: 0 for dimension in CONTENT_DIMENSIONS}
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
    if head in CONTENT_DIMENSIONS:
        return head
    for dimension in CONTENT_DIMENSIONS:
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


def _is_stale_status(status: Any) -> bool:
    normalized = str(status or "").casefold()
    return normalized.startswith("stale") or normalized.startswith("archived") or "stale" in normalized


def _is_tombstone_status(status: Any) -> bool:
    normalized = str(status or "").casefold()
    return (
        "tombstone" in normalized
        or normalized.startswith("rejected")
        or "private_delete" in normalized
        or "deleted" in normalized
    )


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
