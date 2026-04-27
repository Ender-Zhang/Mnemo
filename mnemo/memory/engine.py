from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.ids import new_id
from ..core.jsonutil import dumps, loads
from .query import CONTENT_DIMENSIONS, MemoryQueryPlan, annotate_memory_match, build_memory_query_plan, fuse_ranked_batches
from .safety import append_safety_evidence, scan_memory_candidate

L1_SNAPSHOT_FILENAME = "l1-memory-snapshot.json"
DREAM_REPORTS_DIRNAME = "dream-reports"
DREAM_LATEST_FILENAME = "latest.json"
W0_MEMORY_RETENTION = "memory_candidate"
DEFAULT_W0_CONFIDENCE = 0.62
MIN_W0_CANDIDATE_CHARS = 12
MEMORY_SEARCH_SCOPES = {"memory", "stable", "sessions", "all"}
PRIVATE_DELETE_SUMMARY = "[private memory deleted]"
PRIVATE_DELETE_TOMBSTONE_REASON = "private_delete"
PRIVATE_DELETE_RULE = (
    "Private delete: do not recreate this memory from historical context unless the user explicitly restates it."
)


class MemoryEngine:
    def __init__(self, store: Any):
        self.store = store

    def plan_query(self, query: str) -> MemoryQueryPlan:
        return build_memory_query_plan(query, l1_snapshot=self.load_l1_snapshot())

    def search_with_plan(
        self,
        query: str,
        limit: int = 5,
        *,
        search_scope: str = "memory",
        include_tombstoned: bool = False,
    ) -> dict[str, Any]:
        plan = self.plan_query(query)
        if not plan.original:
            return {"query_plan": plan.metadata(), "matches": []}
        matches, recall_policy = self._search_from_plan(
            plan,
            limit=limit,
            search_scope=search_scope,
            include_tombstoned=include_tombstoned,
        )
        return {
            "query_plan": plan.metadata(),
            "matches": matches,
            "recall_policy": recall_policy,
        }

    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        search_scope: str = "memory",
        include_tombstoned: bool = False,
    ) -> list[dict[str, Any]]:
        return self.search_with_plan(
            query,
            limit=limit,
            search_scope=search_scope,
            include_tombstoned=include_tombstoned,
        )["matches"]

    def _search_from_plan(
        self,
        plan: MemoryQueryPlan,
        *,
        limit: int,
        search_scope: str,
        include_tombstoned: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        normalized_scope = _normalize_search_scope(search_scope)
        bounded_limit = max(1, int(limit))

        results: list[dict[str, Any]] = []
        recall_policy: dict[str, Any] = {}
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
            session_results, session_policy = self._search_session_routes(
                plan,
                limit=bounded_limit,
                include_tombstoned=include_tombstoned,
            )
            results.extend(session_results)
            recall_policy["tombstone_filter"] = session_policy
        return results, recall_policy

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

    def _search_session_routes(
        self,
        plan: MemoryQueryPlan,
        *,
        limit: int,
        include_tombstoned: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        search_session_messages = getattr(self.store, "search_session_messages", None)
        if not search_session_messages:
            return [], _session_tombstone_policy(enabled=not include_tombstoned, tombstones=[], suppressed=[])
        batches: list[tuple[str, str, list[dict[str, Any]]]] = []
        tombstones = [] if include_tombstoned else _session_suppression_tombstones(self.store)
        suppressed: list[dict[str, Any]] = []
        seen_suppressed: set[tuple[str, str]] = set()
        route_limit = min(100, max(limit * 4, limit))
        for route in plan.routes():
            route_items: list[dict[str, Any]] = []
            messages = [
                _session_result(message)
                for message in search_session_messages(route["query"], limit=max(route_limit, 1))
            ]
            for message in messages:
                tombstone = None if include_tombstoned else _matching_session_tombstone(message, tombstones)
                if tombstone:
                    _append_suppressed_session(
                        suppressed,
                        seen_suppressed,
                        message=message,
                        tombstone=tombstone,
                        route=route,
                    )
                    continue
                route_items.append(message)
            batches.append((route["route"], route["query"], route_items))
        return (
            fuse_ranked_batches(batches, plan=plan, limit=max(limit, 1)),
            _session_tombstone_policy(enabled=not include_tombstoned, tombstones=tombstones, suppressed=suppressed),
        )

    def context_cards(
        self,
        query: str,
        limit: int = 5,
        *,
        search_scope: str = "memory",
        include_tombstoned: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            _context_card(item)
            for item in self.search(
                query,
                limit=limit,
                search_scope=search_scope,
                include_tombstoned=include_tombstoned,
            )
        ]

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

    def ingest_working_notes(self, limit: int = 20, *, note_ids: list[str] | set[str] | None = None) -> dict[str, Any]:
        list_notes = getattr(self.store, "list_working_notes", None)
        update_note = getattr(self.store, "update_working_note_status", None)
        if not list_notes or not update_note:
            return {"created": [], "skipped": []}

        selected_note_ids = set(note_ids) if note_ids is not None else None
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        fetch_limit = max(limit, len(selected_note_ids)) if selected_note_ids is not None else limit
        for note in list_notes(status="open", limit=fetch_limit):
            if selected_note_ids is not None and note["id"] not in selected_note_ids:
                continue
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

    def undo_candidate(self, candidate_id: str, reason: str = "user undo") -> dict[str, Any]:
        candidate = self._get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Memory candidate not found: {candidate_id}")

        reason_text = _normalize_space(reason) or "user undo"
        page_results = []
        for page_id in self._promoted_page_ids(candidate_id):
            page = self._get_page(page_id)
            if not page:
                continue
            if _is_tombstone_status(page.get("status")):
                page_results.append(
                    {
                        "page_id": page_id,
                        "status": page.get("status"),
                        "tombstone_id": None,
                    }
                )
                continue
            page_result = self.tombstone_memory(page_id, reason_text, target_type="page")
            page_results.append(
                {
                    "page_id": page_id,
                    "status": page_result.get("status"),
                    "tombstone_id": page_result.get("tombstone_id"),
                }
            )

        if _is_tombstone_status(candidate.get("status")):
            candidate_result: dict[str, Any] = {
                "candidate_id": candidate_id,
                "status": candidate.get("status"),
                "reason": reason_text,
                "tombstone_id": None,
            }
        else:
            candidate_result = self.tombstone_memory(candidate_id, reason_text, target_type="candidate")

        updated = self._get_candidate(candidate_id) or candidate
        page_ids = [item["page_id"] for item in page_results]
        return {
            "candidate_id": candidate_id,
            "status": updated.get("status"),
            "reason": reason_text,
            "page_id": page_ids[0] if page_ids else None,
            "page_ids": page_ids,
            "pages": page_results,
            "tombstone_id": candidate_result.get("tombstone_id"),
        }

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
                    "memory": self._get_page(memory_id),
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
        if normalized_target_type in {"auto", "page"}:
            page = self._get_page(memory_id)
            if page:
                return self._private_delete_page(page, reason_text, redact_source_candidate=True)

        if normalized_target_type in {"auto", "candidate"}:
            candidate = self._get_candidate(memory_id)
            if candidate:
                return self._private_delete_candidate(candidate, reason_text, redact_promoted_pages=True)

        raise ValueError(f"Memory item not found for private delete: {memory_id}")

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
            if decision.get("decayed"):
                self.store.update_memory_page_confidence(page_id, decision["confidence"])
                decayed.append(_compact_decay_change(page, decision))

            if decision.get("stale"):
                self.store.update_memory_page_status(page_id, decision["status"])
                stale_item = _compact_decay_change(page, decision)
                stale_item["status"] = decision["status"]
                staled.append(stale_item)
                updated_page = self._get_page(page_id) or {**page, "status": decision["status"]}
                review_cards.append(_page_review_card("verify_stale", updated_page))

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

    def collect_dream_delta(self, limit: int = 20, *, since: float | None = None) -> dict[str, Any]:
        collected_at = time.time()
        bounded_limit = max(1, int(limit))
        inventory_limit = max(50, bounded_limit * 5)
        notes = [
            _compact_working_note(note)
            for note in _since_filter(
                self.store.list_working_notes(status="open", limit=inventory_limit),
                since=since,
                field="created_at",
            )
        ][:bounded_limit]
        candidates = [
            _compact_candidate(candidate)
            for candidate in _since_filter(
                [
                    candidate
                    for candidate in self.store.list_memory_candidates(status=None, limit=inventory_limit)
                    if candidate.get("status") == "draft"
                    or str(candidate.get("status") or "").startswith("needs_review")
                ],
                since=since,
                field="created_at",
            )
        ][:bounded_limit]
        pages = [
            _compact_page(page)
            for page in _since_filter(
                self.store.list_memory_pages(status=None, limit=inventory_limit),
                since=since,
                field="updated_at",
            )
        ][:bounded_limit]
        list_tombstones = getattr(self.store, "list_memory_tombstones", None)
        tombstones = (
            [
                _compact_tombstone(tombstone)
                for tombstone in _since_filter(list_tombstones(limit=inventory_limit), since=since, field="created_at")
            ][:bounded_limit]
            if list_tombstones
            else []
        )
        list_runs = getattr(self.store, "list_runs", None)
        recent_runs = (
            [
                _compact_run(run)
                for run in _since_filter(list_runs(limit=inventory_limit), since=since, field="created_at")
            ][:bounded_limit]
            if list_runs
            else []
        )
        health = self.health_report(limit=min(10, bounded_limit))
        draft_candidate_ids = [item["id"] for item in candidates if item.get("status") == "draft"]
        note_ids = [item["id"] for item in notes]
        return {
            "kind": "dream_delta",
            "collected_at": collected_at,
            "since": since,
            "counts": {
                "w0_pending": len(notes),
                "memory_candidates": len(candidates),
                "draft_candidates": len(draft_candidate_ids),
                "changed_pages": len(pages),
                "tombstones": len(tombstones),
                "recent_runs": len(recent_runs),
                "review_cards": len(health.get("review_cards", [])),
            },
            "note_ids": note_ids,
            "candidate_ids": draft_candidate_ids,
            "w0_pending": notes,
            "memory_candidates": candidates,
            "changed_pages": pages,
            "tombstones": tombstones,
            "recent_runs": recent_runs,
            "health": {
                "counts": health.get("counts", {}),
                "score": health.get("score", {}),
                "review_cards": health.get("review_cards", []),
            },
        }

    def build_dream_plan(self, delta: dict[str, Any], *, limit: int = 20) -> dict[str, Any]:
        counts = delta.get("counts") if isinstance(delta.get("counts"), dict) else {}
        focus: list[dict[str, Any]] = []
        if counts.get("w0_pending"):
            focus.append({"kind": "ingest_w0", "count": counts["w0_pending"], "tool": "memory_write_candidate"})
        if counts.get("draft_candidates"):
            focus.append({"kind": "review_drafts", "count": counts["draft_candidates"], "tool": "memory_read"})
        if counts.get("review_cards"):
            focus.append({"kind": "memory_health", "count": counts["review_cards"], "tool": "memory_health_report"})
        health_counts = delta.get("health", {}).get("counts", {}) if isinstance(delta.get("health"), dict) else {}
        page_counts = health_counts.get("pages", {}) if isinstance(health_counts.get("pages"), dict) else {}
        if page_counts.get("decay_due_active"):
            focus.append(
                {
                    "kind": "memory_decay_due",
                    "count": page_counts["decay_due_active"],
                    "tool": "memory_decay_stale_pages",
                }
            )
        if counts.get("tombstones"):
            focus.append({"kind": "respect_tombstones", "count": counts["tombstones"], "tool": "memory_search"})
        return {
            "kind": "dream_maintenance_plan",
            "decision_owner": "model",
            "mode": "model_led_decision_surface",
            "budget": {
                "max_items": max(1, int(limit)),
                "max_inbox_items": 5,
                "max_pages_touched": 20,
            },
            "allowed_tools": [
                "memory_search",
                "memory_read",
                "memory_write_candidate",
                "memory_health_report",
                "memory_decay_stale_pages",
                "memory_tombstone",
                "skill_propose_candidate",
                "tool_propose_candidate",
                "eval_propose_case",
                "learning_discard",
            ],
            "focus_candidates": focus,
            "instructions": [
                "Choose 0..N maintenance actions from the delta; do not process the whole store.",
                "Prefer evidence-backed memory candidates, user corrections, conflicts, and tombstones.",
                "Skip low-value items with a reason instead of forcing a workflow step.",
            ],
            "local_fallback": {
                "enabled": True,
                "summary": "Run deterministic candidate consolidation for collected draft candidates only.",
            },
        }

    def dream_maintenance(
        self,
        limit: int = 20,
        min_confidence: float = 0.7,
        *,
        since: float | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        started_at = time.time()
        if since is None:
            latest = self.load_latest_dream_report()
            since = _report_completed_at(latest)
        delta = self.collect_dream_delta(limit=limit, since=since)
        plan = self.build_dream_plan(delta, limit=limit)
        execution = self.dream_consolidate(
            limit=limit,
            min_confidence=min_confidence,
            candidate_ids=delta.get("candidate_ids", []),
            note_ids=delta.get("note_ids", []),
        )
        completed_at = time.time()
        report = {
            "kind": "dream_report",
            "id": new_id("dream"),
            "started_at": started_at,
            "completed_at": completed_at,
            "since": since,
            "duration_s": round(completed_at - started_at, 3),
            "delta": delta,
            "plan": plan,
            "execution": {
                "mode": "local_fallback",
                "result": execution,
            },
            "health_after": self.health_report(limit=min(10, max(1, int(limit)))),
        }
        if persist:
            self.save_dream_report(report)
        return report

    def dream_status(self, limit: int = 20) -> dict[str, Any]:
        latest = self.load_latest_dream_report()
        since = _report_completed_at(latest)
        delta = self.collect_dream_delta(limit=limit, since=since)
        return {
            "kind": "dream_status",
            "generated_at": time.time(),
            "latest": _compact_dream_report(latest) if latest else None,
            "backlog": delta.get("counts", {}),
            "health": delta.get("health", {}),
        }

    def save_dream_report(self, report: dict[str, Any]) -> Path:
        report_id = _safe_report_id(str(report.get("id") or new_id("dream")))
        report["id"] = report_id
        reports_dir = self._dream_reports_path()
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"{report_id}.json"
        path.write_text(dumps(report), encoding="utf-8")
        (reports_dir / DREAM_LATEST_FILENAME).write_text(dumps(report), encoding="utf-8")
        return path

    def load_latest_dream_report(self) -> dict[str, Any] | None:
        return self.load_dream_report(latest=True)

    def load_dream_report(self, report_id: str | None = None, *, latest: bool = False) -> dict[str, Any] | None:
        if latest:
            path = self._dream_reports_path() / DREAM_LATEST_FILENAME
        elif report_id:
            path = self._dream_reports_path() / f"{_safe_report_id(report_id)}.json"
        else:
            return None
        try:
            report = loads(path.read_text(encoding="utf-8"), {})
        except (OSError, TypeError, ValueError):
            return None
        if not isinstance(report, dict) or report.get("kind") != "dream_report":
            return None
        return report

    def dream_consolidate(
        self,
        limit: int = 20,
        min_confidence: float = 0.7,
        *,
        candidate_ids: list[str] | set[str] | None = None,
        note_ids: list[str] | set[str] | None = None,
    ) -> dict[str, Any]:
        w0 = self.ingest_working_notes(limit=limit, note_ids=note_ids)
        selected_candidate_ids = set(candidate_ids or [])
        selected_candidate_ids.update(
            item["candidate_id"]
            for item in w0.get("created", [])
            if item.get("candidate_status") == "draft"
        )
        if candidate_ids is None:
            candidates = self.store.list_memory_candidates(status="draft", limit=limit)
        else:
            candidates = [
                candidate
                for candidate_id in sorted(selected_candidate_ids)
                for candidate in [self._get_candidate(candidate_id)]
                if candidate and candidate.get("status") == "draft"
            ][: max(0, int(limit))]
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

    def _dream_reports_path(self) -> Path:
        return self.store.state_dir / "runs" / DREAM_REPORTS_DIRNAME

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

    def _promoted_page_ids(self, candidate_id: str) -> list[str]:
        page_ids: list[str] = []
        list_links = getattr(self.store, "list_memory_links", None)
        if list_links:
            for link in list_links(candidate_id):
                if link.get("relation") != "promoted_to":
                    continue
                page_id = str(link.get("target_id") or "")
                if page_id and page_id not in page_ids:
                    page_ids.append(page_id)

        list_pages = getattr(self.store, "list_memory_pages", None)
        if list_pages:
            for page in list_pages(status=None, limit=1000):
                page_id = str(page.get("id") or "")
                if page.get("source_candidate_id") == candidate_id and page_id and page_id not in page_ids:
                    page_ids.append(page_id)
        return page_ids

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
            "memory": self._get_page(page_id),
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


def _since_filter(items: list[dict[str, Any]], *, since: float | None, field: str) -> list[dict[str, Any]]:
    if since is None:
        return items
    return [
        item
        for item in items
        if _float_or_zero(item.get(field)) > since
    ]


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


def _session_suppression_tombstones(store: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    list_tombstones = getattr(store, "list_memory_tombstones", None)
    if not list_tombstones:
        return []
    return [
        tombstone
        for tombstone in list_tombstones(limit=limit)
        if _is_private_delete_tombstone(tombstone)
        or _tombstone_signal_terms(tombstone)
        or _tombstone_signal_phrase(tombstone)
    ]


def _matching_session_tombstone(message: dict[str, Any], tombstones: list[dict[str, Any]]) -> dict[str, Any] | None:
    snippet = _normalize_space(str(message.get("snippet") or ""))
    if not snippet:
        return None
    snippet_text = snippet.casefold()
    snippet_terms = set(_keywords(snippet))
    for tombstone in tombstones:
        if _is_private_delete_tombstone(tombstone):
            if _private_delete_tombstone_matches_session(message, tombstone):
                return tombstone
            continue
        phrase = _tombstone_signal_phrase(tombstone)
        if phrase and phrase.casefold() in snippet_text:
            return tombstone
        terms = _tombstone_signal_terms(tombstone)
        if not terms:
            continue
        overlap = terms & snippet_terms
        if len(terms) == 1:
            term = next(iter(terms))
            if len(term) >= 5 and term in overlap:
                return tombstone
            continue
        if len(overlap) >= min(2, len(terms)):
            return tombstone
    return None


def _append_suppressed_session(
    suppressed: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    *,
    message: dict[str, Any],
    tombstone: dict[str, Any],
    route: dict[str, str],
) -> None:
    tombstone_id = str(tombstone.get("id") or "")
    message_id = str(message.get("message_id") or message.get("id") or "")
    key = (message_id, tombstone_id)
    if not key[0] or not key[1] or key in seen:
        return
    seen.add(key)
    suppressed.append(
        {
            "message_id": message_id,
            "conversation_id": message.get("conversation_id"),
            "mission_id": message.get("mission_id"),
            "run_id": message.get("run_id"),
            "tombstone_id": tombstone_id,
            "target_id": tombstone.get("target_id"),
            "target_type": tombstone.get("target_type"),
            "reason": tombstone.get("reason"),
            "route": route.get("route"),
        }
    )


def _session_tombstone_policy(
    *,
    enabled: bool,
    tombstones: list[dict[str, Any]],
    suppressed: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "tombstone_count": len(tombstones),
        "suppressed": len(suppressed),
        "suppressed_items": suppressed[:10],
    }


def _tombstone_signal_phrase(tombstone: dict[str, Any]) -> str:
    summary = _normalize_space(str(tombstone.get("summary") or ""))
    return summary if len(summary) >= 8 else ""


def _tombstone_signal_terms(tombstone: dict[str, Any]) -> set[str]:
    metadata = tombstone.get("metadata") if isinstance(tombstone.get("metadata"), dict) else {}
    values = [
        tombstone.get("summary"),
        metadata.get("title"),
        metadata.get("scope"),
    ]
    return set(_keywords(" ".join(str(value or "") for value in values)))


def _is_private_delete_tombstone(tombstone: dict[str, Any]) -> bool:
    metadata = tombstone.get("metadata") if isinstance(tombstone.get("metadata"), dict) else {}
    return (
        tombstone.get("reason") == PRIVATE_DELETE_TOMBSTONE_REASON
        or metadata.get("redaction") == PRIVATE_DELETE_TOMBSTONE_REASON
    )


def _private_delete_tombstone_matches_session(message: dict[str, Any], tombstone: dict[str, Any]) -> bool:
    evidence_run_id = str(tombstone.get("evidence_run_id") or "")
    return bool(evidence_run_id and evidence_run_id == str(message.get("run_id") or ""))


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


def _compact_dream_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    delta = report.get("delta") if isinstance(report.get("delta"), dict) else {}
    return {
        "id": report.get("id"),
        "started_at": report.get("started_at"),
        "completed_at": report.get("completed_at"),
        "since": report.get("since"),
        "duration_s": report.get("duration_s"),
        "delta_counts": delta.get("counts", {}),
        "execution": {
            "mode": execution.get("mode"),
            "w0_created": len((result.get("w0") or {}).get("created", [])),
            "promoted": len(result.get("promoted", [])),
            "rejected": len(result.get("rejected", [])),
            "skipped": len(result.get("skipped", [])),
            "conflicts": len(result.get("conflicts", [])),
        },
    }


def _report_completed_at(report: dict[str, Any] | None) -> float | None:
    if not report:
        return None
    completed_at = _float_or_zero(report.get("completed_at"))
    return completed_at or None


def _safe_report_id(report_id: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(report_id or "")).strip("._-")
    return normalized or new_id("dream")


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _non_negative_float(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def _metadata_timestamp(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    number_value = _float_or_none(text)
    if number_value is not None:
        return number_value
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


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


def _memory_hash(kind: str, *parts: Any) -> str:
    payload = dumps(
        {
            "kind": kind,
            "parts": [part for part in parts if part is not None],
        }
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def _curation_status(reason: str) -> str:
    slug = _status_reason(reason)
    if slug == "low_usefulness":
        return "archived:low_usefulness"
    return f"tombstoned:{slug}"


def _is_harmful_reason(reason: str) -> bool:
    return _status_reason(reason) == "harmful"


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


def _is_private_delete_status(status: Any) -> bool:
    return str(status or "").casefold().startswith("private_delete")


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
