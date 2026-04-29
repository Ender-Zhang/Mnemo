from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from ..core.jsonutil import dumps, loads
from .cards import _candidate_title, _skip_working_note
from .constants import DEFAULT_W0_CONFIDENCE, L1_SNAPSHOT_FILENAME, MIN_W0_CANDIDATE_CHARS, W0_MEMORY_RETENTION
from .quality import (
    append_quality_evidence,
    candidate_quality_signal,
    compact_quality_signal,
    low_quality_status,
    score_memory_quality,
)
from .query import normalize_memory_dimension
from .safety import append_safety_evidence, scan_memory_candidate
from .snapshot import compile_l1_snapshot_payload
from .utils import (
    _bounded_confidence,
    _compact_safety_scan,
    _fingerprint,
    _is_conflict,
    _is_tombstone_status,
    _keywords,
    _normalize_space,
    _polarity,
    _status_reason,
    _truncate,
)
from .wiki import materialize_memory_page, materialize_memory_pages


NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.72
NEAR_DUPLICATE_CONTAINMENT_THRESHOLD = 0.82


class MemoryLearningMixin:
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
        quality = score_memory_quality(claim, evidence)
        normalized_dimension = normalize_memory_dimension(dimension, fallback="context")
        evidence_with_safety = append_safety_evidence(evidence, scan)
        candidate_id = self.store.add_memory_candidate(
            run_id,
            claim,
            dimension=normalized_dimension,
            scope=scope,
            confidence=confidence,
            evidence=append_quality_evidence(evidence_with_safety, quality),
        )
        status = "draft"
        if scan.get("requires_review"):
            status = f"needs_review:{scan.get('review_reason') or 'memory_safety'}"
            self.store.update_memory_candidate_status(candidate_id, status)
        return {
            "candidate_id": candidate_id,
            "status": status,
            "safety": _compact_safety_scan(scan),
            "quality": compact_quality_signal(quality),
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
                dimension=metadata.get("dimension") or "context",
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
        materialize_memory_pages(self.store.state_dir, pages)
        snapshot = compile_l1_snapshot_payload(self.store, pages, generated_at=time.time())
        path = self._l1_snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(snapshot), encoding="utf-8")
        return snapshot

    def load_or_compile_l1_snapshot(self, limit: int = 50) -> dict[str, Any] | None:
        snapshot = self.load_l1_snapshot()
        if snapshot is not None:
            return snapshot
        if not self.store.list_memory_pages(status="active", limit=1):
            return None
        return self.compile_l1_snapshot(limit=limit)

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
        wiki = materialize_memory_page(self.store.state_dir, page) if page else None
        return {
            "candidate_id": candidate_id,
            "page_id": page_id,
            "status": "promoted",
            "page": page,
            "wiki": wiki,
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

            quality = candidate_quality_signal(candidate)
            quality_status = low_quality_status(quality)
            if quality_status == "rejected":
                result = self.reject_candidate(candidate["id"], "low_quality")
                result["quality"] = compact_quality_signal(quality)
                rejected.append(result)
                continue
            if quality_status == "needs_review":
                status = "needs_review:low_quality"
                self.store.update_memory_candidate_status(candidate["id"], status)
                skipped.append(
                    {
                        "candidate_id": candidate["id"],
                        "status": status,
                        "reason": "below_quality_threshold",
                        "quality": compact_quality_signal(quality),
                    }
                )
                continue

            duplicate_page = self._find_duplicate_page(candidate)
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

    def _find_duplicate_page(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        claim = _normalize_space(candidate.get("claim", ""))
        matches = self.store.search_memory_pages(claim, limit=1)
        exact_match = next(
            (
                page
                for page in matches
                if _fingerprint(page.get("content", "")) == _fingerprint(claim)
            ),
            None,
        )
        if exact_match:
            return exact_match

        candidate_dimension = normalize_memory_dimension(candidate.get("dimension"), fallback="context")
        candidates = self._duplicate_candidate_pages(claim, dimension=candidate_dimension)
        return next(
            (
                page
                for page in candidates
                if _same_memory_dimension(candidate_dimension, page)
                and _is_near_duplicate_claim(claim, str(page.get("content") or ""))
            ),
            None,
        )

    def _duplicate_candidate_pages(self, claim: str, *, dimension: str) -> list[dict[str, Any]]:
        queries = [dimension, *_keywords(claim)[:6]]
        pages_by_id: dict[str, dict[str, Any]] = {}
        for query in queries:
            if not query:
                continue
            for page in self.store.search_memory_pages(str(query), limit=10):
                page_id = str(page.get("id") or "")
                if page_id and page_id not in pages_by_id:
                    pages_by_id[page_id] = page
        return sorted(
            pages_by_id.values(),
            key=lambda page: (
                -float(page.get("confidence") or 0.0),
                -float(page.get("updated_at") or page.get("created_at") or 0.0),
                str(page.get("id") or ""),
            ),
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


def _same_memory_dimension(candidate_dimension: str, page: dict[str, Any]) -> bool:
    title = str(page.get("title") or "")
    title_head = title.split(":", 1)[0] if ":" in title else ""
    page_dimension = normalize_memory_dimension(title_head or page.get("scope"), fallback="context")
    return page_dimension == candidate_dimension


def _is_near_duplicate_claim(left: str, right: str) -> bool:
    if _fingerprint(left) == _fingerprint(right):
        return True
    left_polarity = _polarity(left)
    right_polarity = _polarity(right)
    if {left_polarity, right_polarity} == {"positive", "negative"}:
        return False
    left_terms = set(_keywords(left))
    right_terms = set(_keywords(right))
    if not left_terms or not right_terms:
        return False
    overlap = left_terms & right_terms
    union = left_terms | right_terms
    jaccard = len(overlap) / len(union)
    containment = len(overlap) / min(len(left_terms), len(right_terms))
    return (
        jaccard >= NEAR_DUPLICATE_JACCARD_THRESHOLD
        or containment >= NEAR_DUPLICATE_CONTAINMENT_THRESHOLD
    )
