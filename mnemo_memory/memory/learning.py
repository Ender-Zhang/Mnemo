from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from ..core.jsonutil import dumps, loads
from ..core.log import get_logger, log_event
from .cards import _skip_working_note
from .constants import DEFAULT_W0_CONFIDENCE, L1_SNAPSHOT_FILENAME, MIN_W0_CANDIDATE_CHARS, W0_MEMORY_RETENTION
from .quality import (
    append_quality_evidence,
    candidate_quality_signal,
    compact_quality_signal,
    low_quality_status,
    score_memory_quality,
)
from .query import normalize_memory_dimension
from .profile import compile_l0_profile
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
from .wiki import materialize_memory_page, materialize_memory_pages, memory_page_dimension, memory_page_slug, memory_page_wiki_ref


_LOG = get_logger("learning")

NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.72
NEAR_DUPLICATE_CONTAINMENT_THRESHOLD = 0.82

_DIMENSION_DEFAULT_TOPICS = {
    "identity": "个人资料",
    "cognition": "知识与技能",
    "values": "价值观",
    "goals": "目标",
    "preferences": "服务偏好",
    "relationships": "关系网络",
    "context": "当前情境",
    "history": "经历历史",
    "patterns": "行为模式",
    "boundaries": "边界",
}

_TOPIC_PATTERNS = {
    "cognition": [
        ("编程语言", ("python", "rust", "javascript", "typescript", "go", "语言", "编程")),
        ("AI Agent 研发", ("agent", "llm", "ai ", "模型", "智能体", "机器学习")),
    ],
    "preferences": [
        ("沟通风格", ("沟通", "交流", "回答", "语气", "幽默", "直接", "concise", "direct", "update", "report")),
        ("工具偏好", ("工具", "编辑器", "ide", "cli", "terminal", "browser", "tool")),
        ("预算偏好", ("预算", "花费", "价格", "月预算", "budget", "cost", "price")),
        ("审美偏好", ("设计", "审美", "界面", "ui", "颜色", "diagram", "visual")),
    ],
    "context": [
        ("旅行语境", ("旅行", "旅游", "行程", "攻略", "新疆", "trip", "travel")),
        ("项目语境", ("项目", "代码库", "repo", "mnemo", "workspace")),
    ],
    "goals": [
        ("当前目标", ("目标", "计划", "想要", "希望", "goal", "plan")),
    ],
}


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
        created_at: float | int | str | None = None,
    ) -> dict[str, Any]:
        scan = scan_memory_candidate(claim, evidence)
        quality = score_memory_quality(
            claim,
            evidence,
            write_threshold=getattr(self, "_quality_write_threshold", None),
            draft_threshold=getattr(self, "_quality_draft_threshold", None),
        )
        normalized_dimension = normalize_memory_dimension(dimension, fallback="context")
        evidence_with_safety = append_safety_evidence(evidence, scan)
        candidate_id = self.store.add_memory_candidate(
            run_id,
            claim,
            dimension=normalized_dimension,
            scope=scope,
            confidence=confidence,
            evidence=append_quality_evidence(evidence_with_safety, quality),
            created_at=created_at,
        )
        status = "draft"
        if scan.get("requires_review"):
            status = f"needs_review:{scan.get('review_reason') or 'memory_safety'}"
            self.store.update_memory_candidate_status(candidate_id, status)
        log_event(
            _LOG,
            "candidate_write",
            candidate_id=candidate_id,
            status=status,
            dimension=normalized_dimension,
            quality=quality.get("weighted_avg"),
            risk=scan.get("risk"),
        )
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

    def compile_l0(self, *, limit: int = 50) -> dict[str, Any]:
        pages = self.store.list_memory_pages(status="active", limit=max(1, int(limit)))
        return compile_l0_profile(pages)

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

    def promote_candidate(self, candidate_id: str, *, min_confidence: float = 0.7) -> dict[str, Any]:
        result = self.review_candidate_for_promotion(candidate_id, min_confidence=min_confidence)
        log_event(
            _LOG,
            "candidate_promote_review",
            candidate_id=candidate_id,
            decision=result.get("decision") or result.get("status"),
            page_id=result.get("page_id"),
            page_action=result.get("page_action"),
            reason=result.get("reason") or result.get("gate_reason"),
        )
        return result

    def force_promote_candidate(self, candidate_id: str) -> dict[str, Any]:
        result = self._promote_candidate_unchecked(candidate_id)
        return {
            "kind": "memory_force_promote",
            **result,
        }

    def _snapshot_page_before_mutation(self, page: dict[str, Any], *, change_reason: str, changed_by: str = "system") -> None:
        snapshot_fn = getattr(self.store, "snapshot_page_version", None)
        if snapshot_fn and page and page.get("id"):
            snapshot_fn(str(page["id"]), change_reason=change_reason, changed_by=changed_by)

    def _maybe_index_page_embedding(self, page: dict[str, Any] | None) -> None:
        """Index a freshly written page when an embedding provider is wired.

        Best-effort: a failing embeddings endpoint must never break promotion.
        """
        provider = getattr(self, "_embedding_provider", None)
        model = getattr(self, "_embedding_model", None)
        if provider is None or not model or not page:
            return
        try:
            from .embedding import ensure_page_embeddings

            ensure_page_embeddings(self.store, provider, [page], str(model))
        except (ValueError, OSError, KeyError):
            pass

    def _promote_candidate_unchecked(self, candidate_id: str) -> dict[str, Any]:
        candidate = self._get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Memory candidate not found: {candidate_id}")

        claim = _normalize_space(candidate.get("claim", ""))
        if not claim:
            raise ValueError(f"Memory candidate is empty: {candidate_id}")

        route = self._promotion_page_route(candidate)
        target_page = route.get("page")
        page_action = "merged" if target_page else "created"
        page_title = str(route["title"])
        page_scope = str(target_page.get("scope") if target_page else candidate.get("scope") or "global")
        page_content = _merged_page_content(target_page.get("content", "") if target_page else "", claim)
        confidence = _merged_page_confidence(target_page, candidate)
        metadata = _merged_page_metadata(target_page, candidate, dimension=str(route["dimension"]), topic=str(route["topic"]))
        if target_page:
            self._snapshot_page_before_mutation(target_page, change_reason=f"promote_merge:{candidate_id}", changed_by="dream_consolidate")
            page_id = str(target_page["id"])
            update_page = getattr(self.store, "update_memory_page", None)
            if update_page:
                update_page(
                    page_id,
                    title=page_title,
                    content=page_content,
                    scope=page_scope,
                    source_candidate_id=None,
                    confidence=confidence,
                    status=str(target_page.get("status") or "active"),
                    metadata=metadata,
                )
            else:
                page_id = self.store.upsert_memory_page(
                    page_title,
                    page_content,
                    scope=page_scope,
                    source_candidate_id=None,
                    confidence=confidence,
                    metadata=metadata,
                )
        else:
            page_id = self.store.upsert_memory_page(
                page_title,
                page_content,
                scope=page_scope,
                source_candidate_id=candidate_id,
                confidence=confidence,
                metadata=metadata,
            )
        self.store.update_memory_candidate_status(candidate_id, "promoted")
        self.store.add_memory_link(candidate_id, page_id, "promoted_to", weight=1.0)
        page = self._get_page(page_id)
        wiki = materialize_memory_page(self.store.state_dir, page) if page else None
        self._maybe_index_page_embedding(page)
        log_event(_LOG, "page_write", candidate_id=candidate_id, page_id=page_id, page_action=page_action, scope=page_scope)
        return {
            "candidate_id": candidate_id,
            "page_id": page_id,
            "page_action": page_action,
            "status": "promoted",
            "page": page,
            "wiki": wiki,
        }

    def _promotion_page_route(self, candidate: dict[str, Any]) -> dict[str, Any]:
        claim = _normalize_space(candidate.get("claim", ""))
        dimension = normalize_memory_dimension(candidate.get("dimension"), fallback="context")
        topic = _candidate_page_topic(dimension, claim)
        title = f"{dimension}: {topic}"
        target_page = _select_existing_topic_page(
            self.store.list_memory_pages(status="active", limit=200),
            state_dir=self.store.state_dir,
            dimension=dimension,
            topic=topic,
            claim=claim,
        )
        return {
            "dimension": dimension,
            "topic": topic,
            "title": title,
            "page": target_page,
        }

    def reject_candidate(self, candidate_id: str, reason: str) -> dict[str, Any]:
        candidate = self._get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Memory candidate not found: {candidate_id}")

        reason_text = _normalize_space(reason) or "unspecified"
        status = f"rejected:{_status_reason(reason_text)}"
        self.store.update_memory_candidate_status(candidate_id, status)
        log_event(_LOG, "candidate_reject", candidate_id=candidate_id, status=status, reason=reason_text)
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

    def review_candidate_for_promotion(self, candidate_id: str, min_confidence: float | None = None) -> dict[str, Any]:
        if min_confidence is None:
            min_confidence = float(getattr(self, "_promote_min_confidence", None) or 0.7)
        candidate = self._get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Memory candidate not found: {candidate_id}")
        if candidate.get("status") != "draft":
            return {
                "kind": "memory_promotion_review",
                "candidate_id": candidate_id,
                "status": candidate.get("status"),
                "decision": "skipped",
                "reason": "candidate_not_draft",
            }

        result = self._review_draft_candidate_for_promotion(
            candidate,
            min_confidence=min_confidence,
            seen_claims=set(),
        )
        result.setdefault("kind", "memory_promotion_review")
        result["snapshot"] = self.compile_l1_snapshot(limit=50)
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
            result = self._review_draft_candidate_for_promotion(
                candidate,
                min_confidence=min_confidence,
                seen_claims=seen_claims,
            )
            decision = result.get("decision")
            if decision == "promoted":
                promoted.append(result)
            elif decision == "rejected":
                rejected.append(result)
            elif decision == "conflict":
                conflicts.append(result)
            else:
                skipped.append(result)

        # Auto-resolve conflict candidates with high confidence advantage
        conflict_candidates = [
            c for c in self.store.list_memory_candidates(status=None, limit=limit * 2)
            if str(c.get("status") or "").startswith("needs_review:conflict")
        ]
        resolved: list[dict[str, Any]] = []
        for candidate in conflict_candidates[:limit]:
            conflict_page = self._conflict_page_for_candidate(candidate)
            if not conflict_page:
                continue
            candidate_conf = float(candidate.get("confidence") or 0.0)
            page_conf = float(conflict_page.get("confidence") or 0.0)
            if candidate_conf >= min_confidence and candidate_conf - page_conf >= 0.2:
                result = self.resolve_conflict(candidate["id"], resolution="keep_new")
                result["decision"] = "conflict_resolved"
                result["auto_reason"] = "candidate_confidence_advantage"
                resolved.append(result)
                promoted.append(result)

        return {
            "w0": w0,
            "promoted": promoted,
            "rejected": rejected,
            "skipped": skipped,
            "conflicts": conflicts,
            "resolved": resolved,
            "snapshot": self.compile_l1_snapshot(limit=50),
        }

    def _review_draft_candidate_for_promotion(
        self,
        candidate: dict[str, Any],
        *,
        min_confidence: float,
        seen_claims: set[str],
    ) -> dict[str, Any]:
        claim = _normalize_space(candidate.get("claim", ""))
        fingerprint = _fingerprint(claim)

        if not claim:
            result = self.reject_candidate(candidate["id"], "empty")
            result["decision"] = "rejected"
            return result

        quality = candidate_quality_signal(candidate)
        quality_status = low_quality_status(quality)
        if quality_status == "rejected":
            result = self.reject_candidate(candidate["id"], "low_quality")
            result["decision"] = "rejected"
            result["quality"] = compact_quality_signal(quality)
            return result
        if quality_status == "needs_review":
            status = "needs_review:low_quality"
            self.store.update_memory_candidate_status(candidate["id"], status)
            return {
                "candidate_id": candidate["id"],
                "status": status,
                "decision": "skipped",
                "reason": "below_quality_threshold",
                "quality": compact_quality_signal(quality),
            }

        duplicate_page = self._find_duplicate_page(candidate)
        if fingerprint in seen_claims or duplicate_page:
            if duplicate_page:
                self._reinforce_page(candidate, duplicate_page)
            result = self.reject_candidate(candidate["id"], "duplicate")
            result["decision"] = "rejected"
            return result

        seen_claims.add(fingerprint)
        confidence = float(candidate.get("confidence", 0.0))
        conflict_page = self._find_conflicting_page(candidate)
        if conflict_page:
            result = self._mark_conflict(candidate, conflict_page)
            result["decision"] = "conflict"
            return result

        if confidence < min_confidence:
            return {
                "kind": "memory_promotion_review",
                "candidate_id": candidate["id"],
                "status": candidate.get("status", "draft"),
                "decision": "skipped",
                "reason": "below_confidence_threshold",
            }

        promoted = self._promote_candidate_unchecked(candidate["id"])
        page = promoted.get("page") if isinstance(promoted.get("page"), dict) else {}
        wiki = promoted.get("wiki") if isinstance(promoted.get("wiki"), dict) else {}
        reason = _promotion_approval_reason(
            candidate,
            min_confidence=min_confidence,
            page_action=str(promoted.get("page_action") or ""),
            page=page,
        )
        return {
            "kind": "memory_promotion_review",
            "candidate_id": candidate["id"],
            "status": "promoted",
            "decision": "promoted",
            "reason": reason,
            "page_id": promoted.get("page_id"),
            "page_action": promoted.get("page_action"),
            "page": {
                "id": page.get("id"),
                "title": page.get("title"),
                "status": page.get("status"),
                "confidence": page.get("confidence"),
            },
            "wiki": wiki,
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
                if _page_contains_claim(page, claim)
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
                and _page_has_near_duplicate_claim(page, claim)
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
            "conflict_card": _build_conflict_card(candidate, page),
        }

    def resolve_conflict(
        self,
        candidate_id: str,
        *,
        resolution: str,
    ) -> dict[str, Any]:
        candidate = self._get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        if not str(candidate.get("status") or "").startswith("needs_review:conflict"):
            raise ValueError(f"candidate {candidate_id} is not in conflict status")

        conflict_page = self._conflict_page_for_candidate(candidate)
        resolution = resolution.strip().casefold().replace("-", "_")

        if resolution == "keep_new":
            if conflict_page:
                self.tombstone_memory(
                    conflict_page["id"],
                    f"superseded_by_candidate:{candidate_id}",
                    target_type="page",
                )
            self.store.update_memory_candidate_status(candidate_id, "draft")
            promoted = self._promote_candidate_unchecked(candidate_id)
            return {
                "kind": "conflict_resolution",
                "resolution": "keep_new",
                "candidate_id": candidate_id,
                "superseded_page_id": conflict_page["id"] if conflict_page else None,
                **promoted,
            }
        elif resolution == "keep_old":
            result = self.reject_candidate(candidate_id, "conflict_resolved:keep_old")
            return {
                "kind": "conflict_resolution",
                "resolution": "keep_old",
                "candidate_id": candidate_id,
                "kept_page_id": conflict_page["id"] if conflict_page else None,
                **result,
            }
        elif resolution == "keep_both":
            self.store.update_memory_candidate_status(candidate_id, "draft")
            self.store.update_memory_candidate_status(
                candidate_id,
                "draft",
            )
            promoted = self._promote_candidate_unchecked(candidate_id)
            return {
                "kind": "conflict_resolution",
                "resolution": "keep_both",
                "candidate_id": candidate_id,
                "existing_page_id": conflict_page["id"] if conflict_page else None,
                **promoted,
            }
        else:
            raise ValueError(f"invalid conflict resolution: {resolution} (expected keep_new, keep_old, keep_both)")

    def _conflict_page_for_candidate(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        list_links = getattr(self.store, "list_memory_links", None)
        if list_links:
            for link in list_links(candidate["id"]):
                if link.get("relation") == "conflicts_with":
                    page = self._get_page(str(link.get("target_id") or ""))
                    if page and page.get("status") == "active":
                        return page
        return None


def _build_conflict_card(candidate: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "conflict_decision_card",
        "candidate_id": candidate.get("id"),
        "candidate_claim": _truncate(_normalize_space(str(candidate.get("claim") or "")), limit=200),
        "candidate_dimension": candidate.get("dimension"),
        "candidate_confidence": candidate.get("confidence"),
        "page_id": page.get("id"),
        "page_title": _truncate(_normalize_space(str(page.get("title") or "")), limit=120),
        "page_content": _truncate(_normalize_space(str(page.get("content") or "")), limit=200),
        "page_confidence": page.get("confidence"),
        "options": [
            {"resolution": "keep_new", "description": "Replace existing memory with the new candidate"},
            {"resolution": "keep_old", "description": "Reject the new candidate, keep existing memory"},
            {"resolution": "keep_both", "description": "Keep both as separate memories (no conflict)"},
        ],
    }


def _candidate_page_topic(dimension: str, claim: str) -> str:
    text = f" {_normalize_space(claim).casefold()} "
    for topic, markers in _TOPIC_PATTERNS.get(dimension, []):
        if any(marker.casefold() in text for marker in markers):
            return topic
    return _DIMENSION_DEFAULT_TOPICS.get(dimension, _DIMENSION_DEFAULT_TOPICS["context"])


def _select_existing_topic_page(
    pages: list[dict[str, Any]],
    *,
    state_dir: str | Path,
    dimension: str,
    topic: str,
    claim: str,
) -> dict[str, Any] | None:
    same_dimension = [page for page in pages if _same_memory_dimension(dimension, page)]
    scored = [
        (_topic_page_score(page, state_dir=state_dir, dimension=dimension, topic=topic, claim=claim), page)
        for page in same_dimension
    ]
    scored = [(score, page) for score, page in scored if score > 0]
    if not scored:
        return None
    scored.sort(
        key=lambda item: (
            -item[0],
            -float(item[1].get("updated_at") or item[1].get("created_at") or 0.0),
            str(item[1].get("id") or ""),
        )
    )
    score, page = scored[0]
    return page if score >= 50 else None


def _topic_page_score(
    page: dict[str, Any],
    *,
    state_dir: str | Path,
    dimension: str,
    topic: str,
    claim: str,
) -> int:
    score = 0
    if _page_topic(page) == topic:
        score += 100
    page_keys = _page_topic_keys(page, state_dir=state_dir)
    if _topic_key(topic) in page_keys:
        score += 70
    if dimension == "identity" and topic == _DIMENSION_DEFAULT_TOPICS["identity"]:
        score += 60
    overlap = set(_keywords(claim)) & set(_keywords(f"{page.get('title', '')} {page.get('content', '')}"))
    if overlap:
        score += min(30, 10 * len(overlap))
    return score


def _page_topic(page: dict[str, Any]) -> str:
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    topic = _normalize_space(str(metadata.get("topic") or ""))
    if topic:
        return topic
    title = _normalize_space(str(page.get("title") or ""))
    if ":" in title:
        return title.split(":", 1)[1].strip()
    return title


def _page_topic_keys(page: dict[str, Any], *, state_dir: str | Path) -> set[str]:
    keys = {_topic_key(_page_topic(page)), _topic_key(str(page.get("title") or "")), _topic_key(memory_page_slug(page))}
    try:
        keys.add(_topic_key(memory_page_wiki_ref(state_dir, page)))
    except ValueError:
        pass
    return {key for key in keys if key}


def _topic_key(value: str) -> str:
    return "".join(ch for ch in _normalize_space(value).casefold() if ch.isalnum())


def _merged_page_content(existing_content: str, claim: str) -> str:
    facts = _memory_fact_texts(existing_content)
    claim_text = _normalize_space(claim)
    seen = {_fingerprint(fact) for fact in facts}
    if claim_text and _fingerprint(claim_text) not in seen:
        facts.append(claim_text)
    return "\n".join(f"- {fact}" for fact in facts) or claim_text


def _promotion_approval_reason(
    candidate: dict[str, Any],
    *,
    min_confidence: float,
    page_action: str,
    page: dict[str, Any],
) -> str:
    confidence = _bounded_confidence(candidate.get("confidence"), 0.0)
    action_text = "merged into an existing stable page" if page_action == "merged" else "created a stable page"
    page_title = _normalize_space(str(page.get("title") or ""))
    title_text = f" ({page_title})" if page_title else ""
    return (
        "passed quality and confidence gates; "
        f"confidence {confidence:.2f} >= {min_confidence:.2f}; "
        f"{action_text}{title_text}"
    )


def _memory_fact_texts(content: str) -> list[str]:
    facts: list[str] = []
    seen: set[str] = set()
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line or line == "_No memory body._" or line.startswith("#"):
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        if not line:
            continue
        fingerprint = _fingerprint(line)
        if fingerprint in seen:
            continue
        facts.append(line)
        seen.add(fingerprint)
    return facts


def _page_contains_claim(page: dict[str, Any], claim: str) -> bool:
    claim_fingerprint = _fingerprint(claim)
    return any(_fingerprint(fact) == claim_fingerprint for fact in _memory_fact_texts(str(page.get("content") or "")))


def _page_has_near_duplicate_claim(page: dict[str, Any], claim: str) -> bool:
    facts = _memory_fact_texts(str(page.get("content") or ""))
    if not facts:
        facts = [str(page.get("content") or "")]
    return any(_is_near_duplicate_claim(claim, fact) for fact in facts)


def _merged_page_confidence(target_page: dict[str, Any] | None, candidate: dict[str, Any]) -> float:
    candidate_confidence = float(candidate.get("confidence", 0.7))
    if not target_page:
        return candidate_confidence
    page_confidence = float(target_page.get("confidence", 0.0))
    return min(1.0, max(page_confidence, candidate_confidence))


def _merged_page_metadata(
    target_page: dict[str, Any] | None,
    candidate: dict[str, Any],
    *,
    dimension: str,
    topic: str,
) -> dict[str, Any]:
    metadata = dict(target_page.get("metadata") or {}) if target_page else {}
    metadata["dimension"] = dimension
    metadata["topic"] = topic
    source_ids = _string_list(metadata.get("source_candidate_ids"))
    if target_page and target_page.get("source_candidate_id"):
        source_ids.append(str(target_page["source_candidate_id"]))
    source_ids.append(str(candidate.get("id") or ""))
    metadata["source_candidate_ids"] = _dedupe_strings(source_ids, limit=50)
    return metadata


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _dedupe_strings(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
        if len(result) >= limit:
            break
    return result


def _same_memory_dimension(candidate_dimension: str, page: dict[str, Any]) -> bool:
    return memory_page_dimension(page) == candidate_dimension


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
