from __future__ import annotations

from pathlib import Path
import re
import time
from typing import Any

from ..core.ids import new_id
from ..core.jsonutil import dumps, loads
from .cards import _compact_candidate, _compact_page, _compact_run, _compact_tombstone, _compact_working_note
from .constants import DREAM_LATEST_FILENAME, DREAM_REPORTS_DIRNAME
from .utils import _bounded_confidence, _float_or_zero, _normalize_space, _truncate
from .wiki import materialize_memory_page


ADVANCED_DREAM_LOW_RISK_TOOLS = {"memory_link_pages"}
ADVANCED_DREAM_PROPOSAL_TOOLS = {
    "memory_rewrite_page",
    "memory_merge_pages",
    "memory_split_page",
    "memory_reconcile_conflict",
}
ADVANCED_DREAM_TOOLS = ADVANCED_DREAM_LOW_RISK_TOOLS | ADVANCED_DREAM_PROPOSAL_TOOLS


class MemoryDreamMixin:
    def collect_dream_delta(self, limit: int = 20, *, since: float | None = None) -> dict[str, Any]:
        collected_at = time.time()
        bounded_limit = max(1, int(limit))
        inventory_limit = max(50, bounded_limit * 5)
        open_notes = self.store.list_working_notes(status="open", limit=inventory_limit)
        notes = [_compact_working_note(note) for note in open_notes][:bounded_limit]
        unresolved_candidates = [
            candidate
            for candidate in self.store.list_memory_candidates(status=None, limit=inventory_limit)
            if candidate.get("status") == "draft"
            or str(candidate.get("status") or "").startswith("needs_review")
        ]
        candidates = [
            _compact_candidate(candidate)
            for candidate in unresolved_candidates
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

    def build_dream_plan(self, delta: dict[str, Any], *, limit: int = 20, advanced_dreaming: bool = False) -> dict[str, Any]:
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
        allowed_tools = [
            "memory_search",
            "memory_read",
            "memory_write_candidate",
            "memory_health_report",
            "memory_decay_stale_pages",
            "memory_tombstone",
            "memory_promote_candidate",
            "memory_reject_candidate",
            "learning_discard",
        ]
        if advanced_dreaming:
            allowed_tools.extend(sorted(ADVANCED_DREAM_TOOLS))
        instructions = [
            "Choose 0..N maintenance actions from the delta; do not process the whole store.",
            "Stable memory changes happen only when the model selects an explicit maintenance tool.",
            "Prefer evidence-backed memory candidates, user corrections, conflicts, and tombstones.",
            "User-provided private profile/contact facts may be promoted when they are stable and useful; do not reject solely because they are private.",
            "Reject or forget private content only when the user asked not to save it, asked to delete it, or the source is unsafe/untrusted.",
            "Skip low-value items with a reason instead of forcing a workflow step.",
        ]
        if advanced_dreaming:
            instructions.extend(
                [
                    "Advanced Dreaming is enabled with semi-auto execution.",
                    "Use memory_link_pages for additive, non-destructive links.",
                    "Use memory_rewrite_page, memory_merge_pages, memory_split_page, or memory_reconcile_conflict only as high-risk proposals; they will require operator confirmation.",
                    "For high-risk proposals, include a clear title, rationale, and before/after fields.",
                ]
            )
        return {
            "kind": "dream_maintenance_plan",
            "decision_owner": "model",
            "mode": "model_led_tool_use",
            "advanced_dreaming": bool(advanced_dreaming),
            "execution_policy": "semi_auto" if advanced_dreaming else "standard",
            "budget": {
                "max_items": max(1, int(limit)),
                "max_inbox_items": 5,
                "max_pages_touched": 20,
            },
            "allowed_tools": allowed_tools,
            "focus_candidates": focus,
            "instructions": instructions,
        }

    def dream_maintenance(
        self,
        limit: int = 20,
        min_confidence: float = 0.7,
        *,
        since: float | None = None,
        persist: bool = True,
        actions: list[dict[str, Any]] | None = None,
        plan: dict[str, Any] | None = None,
        advanced_dreaming: bool = False,
        execution_policy: str = "semi_auto",
    ) -> dict[str, Any]:
        started_at = time.time()
        if since is None:
            latest = self.load_latest_dream_report()
            since = _report_completed_at(latest)
        delta = self.collect_dream_delta(limit=limit, since=since)
        dream_plan = self.build_dream_plan(delta, limit=limit, advanced_dreaming=advanced_dreaming)
        dream_actions = _dream_actions_from_inputs(actions=actions, plan=plan)
        if dream_actions:
            dream_plan["proposed_actions"] = [
                _compact_dream_action_request(action, index)
                for index, action in enumerate(dream_actions[: max(1, int(limit))])
            ]
        report_id = new_id("dream")
        action_execution = (
            self.apply_dream_actions(
                dream_actions,
                limit=limit,
                min_confidence=min_confidence,
                report_id=report_id,
                advanced_dreaming=advanced_dreaming,
                execution_policy=execution_policy,
            )
            if dream_actions
            else None
        )
        snapshot = self.compile_l1_snapshot(limit=50)
        execution = {
            "actions": action_execution or {
                "kind": "dream_memory_action_result",
                "counts": {"requested": 0, "applied": 0, "skipped": 0},
                "applied": [],
                "skipped": [],
            },
            "snapshot": snapshot,
        }
        completed_at = time.time()
        report = {
            "kind": "dream_report",
            "id": report_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "since": since,
            "duration_s": round(completed_at - started_at, 3),
            "advanced_dreaming": bool(advanced_dreaming),
            "execution_policy": _normalize_execution_policy(execution_policy),
            "delta": delta,
            "plan": dream_plan,
            "execution": {
                "mode": "model_actions" if action_execution else "model_required",
                "result": execution,
            },
            "health_after": self.health_report(limit=min(10, max(1, int(limit)))),
        }
        if persist:
            self.save_dream_report(report)
        return report

    def apply_dream_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        limit: int = 20,
        min_confidence: float = 0.7,
        report_id: str | None = None,
        advanced_dreaming: bool = False,
        execution_policy: str = "semi_auto",
    ) -> dict[str, Any]:
        bounded_limit = max(0, int(limit))
        requested = list(actions or [])[:bounded_limit]
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        proposals: list[dict[str, Any]] = []
        normalized_policy = _normalize_execution_policy(execution_policy)

        for index, raw_action in enumerate(requested):
            action = _normalize_dream_action(raw_action, index)
            action_id = action.get("id") or f"dream_action_{index + 1}"
            if action.get("error"):
                skipped.append(_dream_action_skip(action_id, action.get("tool"), action["error"]))
                continue

            tool = action.get("tool")
            arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            try:
                if tool == "memory_tombstone":
                    applied.append(self._apply_dream_tombstone_action(action_id, arguments))
                    continue
                if tool == "memory_decay_stale_pages":
                    applied.append(self._apply_dream_decay_action(action_id, arguments, limit=bounded_limit))
                    continue
                if tool == "memory_link_pages":
                    if not advanced_dreaming:
                        skipped.append(_dream_action_skip(action_id, tool, "advanced_dreaming_disabled"))
                    elif normalized_policy != "semi_auto":
                        skipped.append(_dream_action_skip(action_id, tool, f"unsupported_execution_policy:{normalized_policy}"))
                    else:
                        applied.append(self._apply_dream_link_action(action_id, arguments))
                    continue
                if tool in ADVANCED_DREAM_PROPOSAL_TOOLS:
                    if not advanced_dreaming:
                        skipped.append(_dream_action_skip(action_id, tool, "advanced_dreaming_disabled"))
                    elif normalized_policy != "semi_auto":
                        skipped.append(_dream_action_skip(action_id, tool, f"unsupported_execution_policy:{normalized_policy}"))
                    else:
                        proposal = self._store_dream_proposal(action_id, tool, arguments, report_id=report_id)
                        proposals.append(proposal)
                        applied.append(_compact_dream_proposal_result(action_id, tool, proposal))
                    continue
                if tool == "memory_promote_candidate":
                    applied.append(
                        self._apply_dream_promote_action(
                            action_id,
                            arguments,
                            min_confidence=min_confidence,
                        )
                    )
                    continue
                if tool == "memory_reject_candidate":
                    applied.append(self._apply_dream_reject_action(action_id, arguments))
                    continue
                skipped.append(_dream_action_skip(action_id, tool, "unsupported_tool"))
            except (TypeError, ValueError) as exc:
                skipped.append(_dream_action_skip(action_id, tool, str(exc)))

        return {
            "kind": "dream_memory_action_result",
            "counts": {
                "requested": len(requested),
                "applied": len(applied),
                "skipped": len(skipped),
            },
            "applied": applied,
            "skipped": skipped,
            "proposals": proposals,
        }

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

    def _dream_reports_path(self) -> Path:
        return self.store.state_dir / "runs" / DREAM_REPORTS_DIRNAME

    def _apply_dream_tombstone_action(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = _normalize_space(
            str(arguments.get("memory_id") or arguments.get("id") or arguments.get("target_id") or "")
        )
        reason = _normalize_space(str(arguments.get("reason") or ""))
        if not memory_id:
            raise ValueError("missing memory_id")
        if not reason:
            raise ValueError("missing reason")
        result = self.tombstone_memory(
            memory_id,
            reason,
            target_type=str(arguments.get("target_type") or "auto"),
            replacement_id=arguments.get("replacement_id"),
            eval_run_id=arguments.get("eval_run_id") or arguments.get("run_id"),
        )
        return _compact_dream_tombstone_result(action_id, result)

    def _apply_dream_decay_action(
        self,
        action_id: str,
        arguments: dict[str, Any],
        *,
        limit: int,
    ) -> dict[str, Any]:
        action_limit = _bounded_action_limit(arguments.get("limit"), default=max(1, limit))
        stale_confidence = _bounded_confidence(arguments.get("stale_confidence"), 0.35)
        result = self.decay_stale_pages(limit=action_limit, stale_confidence=stale_confidence)
        return _compact_dream_decay_result(action_id, result)

    def _apply_dream_promote_action(
        self,
        action_id: str,
        arguments: dict[str, Any],
        *,
        min_confidence: float,
    ) -> dict[str, Any]:
        candidate_id = _normalize_space(
            str(arguments.get("candidate_id") or arguments.get("id") or arguments.get("memory_id") or "")
        )
        if not candidate_id:
            raise ValueError("missing candidate_id")
        result = self.review_candidate_for_promotion(
            candidate_id,
            min_confidence=_bounded_confidence(arguments.get("min_confidence"), min_confidence),
        )
        action_reason = _normalize_space(
            str(arguments.get("reason") or arguments.get("rationale") or arguments.get("why") or "")
        )
        if action_reason:
            if result.get("reason") and result.get("reason") != action_reason:
                result = {**result, "gate_reason": result.get("reason"), "reason": action_reason}
            else:
                result = {**result, "reason": action_reason}
        return _compact_dream_promote_result(action_id, result)

    def _apply_dream_reject_action(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        candidate_id = _normalize_space(
            str(arguments.get("candidate_id") or arguments.get("id") or arguments.get("memory_id") or "")
        )
        reason = _normalize_space(str(arguments.get("reason") or ""))
        if not candidate_id:
            raise ValueError("missing candidate_id")
        if not reason:
            raise ValueError("missing reason")
        result = self.reject_candidate(candidate_id, reason)
        return _compact_dream_reject_result(action_id, result)

    def _apply_dream_link_action(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        source_id = _normalize_space(str(arguments.get("source_id") or arguments.get("page_id") or ""))
        target_id = _normalize_space(str(arguments.get("target_id") or arguments.get("related_page_id") or ""))
        relation = _normalize_space(str(arguments.get("relation") or "related"))
        if not source_id:
            raise ValueError("missing source_id")
        if not target_id:
            raise ValueError("missing target_id")
        if source_id == target_id:
            raise ValueError("source_id and target_id must differ")
        if not self.store.get_memory_page(source_id):
            raise ValueError(f"source page not found: {source_id}")
        if not self.store.get_memory_page(target_id):
            raise ValueError(f"target page not found: {target_id}")
        weight = _bounded_confidence(arguments.get("weight"), 1.0)
        link_id = self.store.add_memory_link(source_id, target_id, relation or "related", weight=weight)
        return {
            "action_id": action_id,
            "tool": "memory_link_pages",
            "status": "applied",
            "link_id": link_id,
            "source_id": source_id,
            "target_id": target_id,
            "relation": relation or "related",
            "weight": weight,
        }

    def _store_dream_proposal(
        self,
        action_id: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        report_id: str | None,
    ) -> dict[str, Any]:
        before = _proposal_before(self.store, tool, arguments)
        after = _proposal_after(tool, arguments)
        title = _proposal_title(tool, arguments, before)
        rationale = _normalize_space(
            str(arguments.get("rationale") or arguments.get("reason") or arguments.get("why") or "")
        )
        action = {
            "action_id": action_id,
            "tool": tool,
            "arguments": arguments,
        }
        return self.store.add_dream_proposal(
            report_id=report_id,
            tool=tool,
            title=title,
            rationale=rationale,
            risk="high",
            status="pending",
            action=action,
            before=before,
            after=after,
        )

    def dream_proposals(self, *, status: str | None = "pending", limit: int = 50) -> dict[str, Any]:
        proposals = self.store.list_dream_proposals(status=status, limit=limit)
        return {
            "kind": "dream_proposals",
            "status": status,
            "count": len(proposals),
            "proposals": proposals,
        }

    def reject_dream_proposal(self, proposal_id: str, reason: str = "operator_rejected") -> dict[str, Any]:
        proposal = _require_pending_proposal(self.store, proposal_id)
        updated = self.store.update_dream_proposal_status(
            proposal["id"],
            "rejected",
            decision={"reason": _normalize_space(reason) or "operator_rejected"},
        )
        return {
            "kind": "dream_proposal_reject",
            "proposal_id": updated["id"],
            "proposal": updated,
        }

    def apply_dream_proposal(self, proposal_id: str) -> dict[str, Any]:
        proposal = _require_pending_proposal(self.store, proposal_id)
        tool = str(proposal.get("tool") or "")
        action = proposal.get("action") if isinstance(proposal.get("action"), dict) else {}
        arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        if tool == "memory_link_pages":
            result = self._apply_dream_link_action(str(action.get("action_id") or proposal["id"]), arguments)
        elif tool == "memory_rewrite_page":
            result = self._apply_rewrite_proposal(arguments)
        elif tool == "memory_merge_pages":
            result = self._apply_merge_proposal(arguments)
        elif tool == "memory_split_page":
            result = self._apply_split_proposal(arguments)
        elif tool == "memory_reconcile_conflict":
            result = self._apply_reconcile_proposal(arguments)
        else:
            raise ValueError(f"unsupported dream proposal tool: {tool}")
        updated = self.store.update_dream_proposal_status(
            proposal["id"],
            "applied",
            decision={"result": result},
        )
        return {
            "kind": "dream_proposal_apply",
            "proposal_id": updated["id"],
            "result": result,
            "proposal": updated,
        }

    def _apply_rewrite_proposal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        page_id = _proposal_page_id(arguments)
        page = _require_page(self.store, page_id)
        next_title = _normalize_space(str(arguments.get("title") or arguments.get("proposed_title") or page.get("title") or ""))
        next_content = _normalize_space(str(arguments.get("content") or arguments.get("proposed_content") or page.get("content") or ""))
        if not next_content:
            raise ValueError("rewrite proposal requires proposed content")
        metadata = dict(page.get("metadata") if isinstance(page.get("metadata"), dict) else {})
        metadata.setdefault("dream_reorganized", True)
        self.store.update_memory_page(
            page_id,
            title=next_title or str(page.get("title") or page_id),
            content=next_content,
            scope=str(arguments.get("scope") or page.get("scope") or "global"),
            source_candidate_id=page.get("source_candidate_id"),
            confidence=_bounded_confidence(arguments.get("confidence"), _float_or_zero(page.get("confidence")) or 0.7),
            status=str(page.get("status") or "active"),
            metadata=metadata,
        )
        updated = _require_page(self.store, page_id)
        wiki = materialize_memory_page(self.store.state_dir, updated)
        snapshot = self.compile_l1_snapshot(limit=50)
        return {"tool": "memory_rewrite_page", "page": updated, "wiki": wiki, "snapshot": snapshot}

    def _apply_merge_proposal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        target_id = _normalize_space(str(arguments.get("target_page_id") or arguments.get("page_id") or ""))
        if not target_id:
            raise ValueError("merge proposal requires target_page_id")
        target = _require_page(self.store, target_id)
        source_ids = _proposal_source_page_ids(arguments, exclude={target_id})
        next_content = _normalize_space(str(arguments.get("content") or arguments.get("proposed_content") or ""))
        if not next_content:
            contents = [str(target.get("content") or "")]
            for source_id in source_ids:
                source = self.store.get_memory_page(source_id)
                if source:
                    contents.append(str(source.get("content") or ""))
            next_content = "\n".join(part for part in contents if part)
        next_title = _normalize_space(str(arguments.get("title") or arguments.get("proposed_title") or target.get("title") or ""))
        metadata = dict(target.get("metadata") if isinstance(target.get("metadata"), dict) else {})
        metadata.setdefault("merged_page_ids", [])
        metadata["merged_page_ids"] = sorted({*metadata.get("merged_page_ids", []), *source_ids})
        self.store.update_memory_page(
            target_id,
            title=next_title or str(target.get("title") or target_id),
            content=next_content,
            scope=str(arguments.get("scope") or target.get("scope") or "global"),
            source_candidate_id=target.get("source_candidate_id"),
            confidence=_bounded_confidence(arguments.get("confidence"), _float_or_zero(target.get("confidence")) or 0.7),
            status=str(target.get("status") or "active"),
            metadata=metadata,
        )
        tombstoned: list[dict[str, Any]] = []
        for source_id in source_ids:
            if self.store.get_memory_page(source_id):
                tombstoned.append(
                    self.tombstone_memory(source_id, f"merged_into:{target_id}", target_type="page", replacement_id=target_id)
                )
        updated = _require_page(self.store, target_id)
        wiki = materialize_memory_page(self.store.state_dir, updated)
        snapshot = self.compile_l1_snapshot(limit=50)
        return {"tool": "memory_merge_pages", "target_page": updated, "tombstoned": tombstoned, "wiki": wiki, "snapshot": snapshot}

    def _apply_split_proposal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        page_id = _proposal_page_id(arguments)
        page = _require_page(self.store, page_id)
        proposed_pages = arguments.get("proposed_pages") or arguments.get("pages")
        if not isinstance(proposed_pages, list) or not proposed_pages:
            raise ValueError("split proposal requires proposed_pages")
        created: list[dict[str, Any]] = []
        for item in proposed_pages:
            if not isinstance(item, dict):
                continue
            title = _normalize_space(str(item.get("title") or ""))
            content = _normalize_space(str(item.get("content") or item.get("summary") or ""))
            if not title or not content:
                continue
            new_page_id = self.store.create_memory_page(
                title,
                content,
                scope=str(item.get("scope") or page.get("scope") or "global"),
                source_candidate_id=page.get("source_candidate_id"),
                confidence=_bounded_confidence(item.get("confidence"), _float_or_zero(page.get("confidence")) or 0.7),
                status="active",
                metadata={"split_from_page_id": page_id, "dream_reorganized": True},
            )
            new_page = _require_page(self.store, new_page_id)
            materialize_memory_page(self.store.state_dir, new_page)
            created.append(new_page)
        if not created:
            raise ValueError("split proposal produced no valid pages")
        tombstone = self.tombstone_memory(page_id, "split_into_smaller_pages", target_type="page", replacement_id=created[0]["id"])
        snapshot = self.compile_l1_snapshot(limit=50)
        return {"tool": "memory_split_page", "source_page_id": page_id, "created_pages": created, "tombstone": tombstone, "snapshot": snapshot}

    def _apply_reconcile_proposal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._apply_rewrite_proposal(arguments)
        conflict_page_id = _normalize_space(str(arguments.get("conflict_page_id") or arguments.get("conflicting_page_id") or ""))
        if conflict_page_id and self.store.get_memory_page(conflict_page_id):
            result["conflict_tombstone"] = self.tombstone_memory(
                conflict_page_id,
                f"reconciled_with:{result['page']['id']}",
                target_type="page",
                replacement_id=result["page"]["id"],
            )
        result["tool"] = "memory_reconcile_conflict"
        return result


def _since_filter(items: list[dict[str, Any]], *, since: float | None, field: str) -> list[dict[str, Any]]:
    if since is None:
        return items
    return [
        item
        for item in items
        if _float_or_zero(item.get(field)) > since
    ]


def _normalize_execution_policy(value: str | None) -> str:
    clean = str(value or "semi_auto").strip().casefold().replace("-", "_")
    return clean if clean in {"semi_auto"} else "semi_auto"


def _require_page(store: Any, page_id: str) -> dict[str, Any]:
    clean_id = _normalize_space(str(page_id or ""))
    if not clean_id:
        raise ValueError("page_id is required")
    page = store.get_memory_page(clean_id)
    if not page:
        raise ValueError(f"memory page not found: {clean_id}")
    return page


def _require_pending_proposal(store: Any, proposal_id: str) -> dict[str, Any]:
    clean_id = _normalize_space(str(proposal_id or ""))
    if not clean_id:
        raise ValueError("proposal_id is required")
    proposal = store.get_dream_proposal(clean_id)
    if not proposal:
        raise ValueError(f"dream proposal not found: {clean_id}")
    if proposal.get("status") != "pending":
        raise ValueError(f"dream proposal is not pending: {clean_id}")
    return proposal


def _proposal_page_id(arguments: dict[str, Any]) -> str:
    page_id = _normalize_space(
        str(arguments.get("page_id") or arguments.get("memory_id") or arguments.get("target_page_id") or "")
    )
    if not page_id:
        raise ValueError("proposal requires page_id")
    return page_id


def _proposal_source_page_ids(arguments: dict[str, Any], *, exclude: set[str] | None = None) -> list[str]:
    raw_ids = arguments.get("source_page_ids") or arguments.get("page_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [part.strip() for part in raw_ids.split(",")]
    excluded = exclude or set()
    ids: list[str] = []
    if isinstance(raw_ids, list):
        for value in raw_ids:
            clean_id = _normalize_space(str(value or ""))
            if clean_id and clean_id not in excluded and clean_id not in ids:
                ids.append(clean_id)
    return ids


def _proposal_before(store: Any, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool == "memory_merge_pages":
        target_id = _normalize_space(str(arguments.get("target_page_id") or arguments.get("page_id") or ""))
        source_ids = _proposal_source_page_ids(arguments, exclude={target_id} if target_id else set())
        return {
            "target_page": store.get_memory_page(target_id) if target_id else None,
            "source_pages": [page for page in (store.get_memory_page(page_id) for page_id in source_ids) if page],
        }
    if tool == "memory_split_page":
        page_id = _normalize_space(str(arguments.get("page_id") or arguments.get("memory_id") or ""))
        return {"page": store.get_memory_page(page_id) if page_id else None}
    if tool in {"memory_rewrite_page", "memory_reconcile_conflict"}:
        page_id = _normalize_space(str(arguments.get("page_id") or arguments.get("memory_id") or arguments.get("target_page_id") or ""))
        conflict_page_id = _normalize_space(str(arguments.get("conflict_page_id") or arguments.get("conflicting_page_id") or ""))
        return {
            "page": store.get_memory_page(page_id) if page_id else None,
            "conflict_page": store.get_memory_page(conflict_page_id) if conflict_page_id else None,
        }
    return {}


def _proposal_after(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool == "memory_split_page":
        proposed_pages = arguments.get("proposed_pages") or arguments.get("pages") or []
        return {"proposed_pages": proposed_pages if isinstance(proposed_pages, list) else []}
    output: dict[str, Any] = {}
    for key in ("title", "proposed_title", "content", "proposed_content", "scope", "confidence", "relation"):
        if key in arguments:
            output[key] = arguments[key]
    if tool == "memory_merge_pages":
        output["target_page_id"] = arguments.get("target_page_id") or arguments.get("page_id")
        output["source_page_ids"] = _proposal_source_page_ids(arguments)
    if tool == "memory_reconcile_conflict":
        output["conflict_page_id"] = arguments.get("conflict_page_id") or arguments.get("conflicting_page_id")
    return output


def _proposal_title(tool: str, arguments: dict[str, Any], before: dict[str, Any]) -> str:
    explicit = _normalize_space(str(arguments.get("title") or arguments.get("proposal_title") or ""))
    if explicit:
        return explicit
    if tool == "memory_rewrite_page":
        page = before.get("page") if isinstance(before.get("page"), dict) else {}
        return f"重写稳定记忆：{page.get('title') or arguments.get('page_id') or 'memory page'}"
    if tool == "memory_merge_pages":
        return "合并重复稳定记忆页"
    if tool == "memory_split_page":
        page = before.get("page") if isinstance(before.get("page"), dict) else {}
        return f"拆分稳定记忆：{page.get('title') or arguments.get('page_id') or 'memory page'}"
    if tool == "memory_reconcile_conflict":
        return "处理稳定记忆冲突"
    return tool.replace("_", " ")

def _compact_dream_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    delta = report.get("delta") if isinstance(report.get("delta"), dict) else {}
    actions = result.get("actions") if isinstance(result.get("actions"), dict) else {}
    action_counts = actions.get("counts") if isinstance(actions.get("counts"), dict) else {}
    proposals = actions.get("proposals") if isinstance(actions.get("proposals"), list) else []
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    review_results = _dream_review_results(actions.get("applied"))
    reject_reasons = _dream_reject_reasons(actions.get("applied"))
    return {
        "id": report.get("id"),
        "started_at": report.get("started_at"),
        "completed_at": report.get("completed_at"),
        "since": report.get("since"),
        "duration_s": report.get("duration_s"),
        "advanced_dreaming": bool(report.get("advanced_dreaming")),
        "execution_policy": report.get("execution_policy"),
        "delta_counts": delta.get("counts", {}),
        "execution": {
            "mode": execution.get("mode"),
            "w0_created": len((result.get("w0") or {}).get("created", [])),
            "promoted": len(result.get("promoted", [])),
            "rejected": len(result.get("rejected", [])) or len(reject_reasons),
            "skipped": len(result.get("skipped", [])),
            "conflicts": len(result.get("conflicts", [])),
            "actions_applied": action_counts.get("applied", 0),
            "actions_skipped": action_counts.get("skipped", 0),
            "proposals_pending": len([item for item in proposals if isinstance(item, dict) and item.get("status") == "pending"]),
            "tool_calls": counts.get("tool_calls", 0),
            "review_results": review_results,
            "reject_reasons": reject_reasons,
        },
    }

def _dream_review_results(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        return []
    results: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        tool = str(action.get("tool") or "")
        if tool not in {"memory_promote_candidate", "memory_reject_candidate"}:
            continue
        item: dict[str, Any] = {
            "tool": tool,
            "status": action.get("status"),
            "decision": _dream_review_decision(action),
        }
        for key in ("candidate_id", "page_id", "action_id", "reason", "gate_reason", "page_action"):
            value = action.get(key)
            if value:
                item[key] = _truncate(str(value), limit=160) if key in {"reason", "gate_reason"} else value
        if action.get("page_title"):
            item["page_title"] = _truncate(str(action.get("page_title")), limit=120)
        results.append(item)
    return results[:20]


def _dream_review_decision(action: dict[str, Any]) -> str:
    decision = str(action.get("decision") or "").strip()
    if decision:
        return decision
    tool = str(action.get("tool") or "")
    status = str(action.get("status") or "")
    if tool == "memory_reject_candidate" or status.startswith("rejected"):
        return "rejected"
    if status == "promoted":
        return "promoted"
    return status or "applied"


def _dream_reject_reasons(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        return []
    rejected: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        tool = str(action.get("tool") or "")
        decision = str(action.get("decision") or "")
        status = str(action.get("status") or "")
        if tool != "memory_reject_candidate" and decision != "rejected" and not status.startswith("rejected"):
            continue
        reason = _normalize_space(str(action.get("reason") or ""))
        if not reason:
            continue
        item = {
            "reason": _truncate(reason, limit=160),
        }
        for key in ("candidate_id", "action_id", "tool", "status", "decision"):
            value = action.get(key)
            if value:
                item[key] = value
        rejected.append(item)
    return rejected[:10]

def _dream_actions_from_inputs(
    *,
    actions: list[dict[str, Any]] | None,
    plan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    if isinstance(plan, dict):
        for key in ("actions", "maintenance_actions", "tool_calls"):
            value = plan.get(key)
            if isinstance(value, list):
                collected.extend(item for item in value if isinstance(item, dict))
    if isinstance(actions, list):
        collected.extend(item for item in actions if isinstance(item, dict))
    return collected

def _normalize_dream_action(raw_action: dict[str, Any], index: int) -> dict[str, Any]:
    action_id = str(raw_action.get("id") or raw_action.get("call_id") or f"dream_action_{index + 1}")
    tool: Any = raw_action.get("tool") or raw_action.get("name") or raw_action.get("action") or raw_action.get("type")
    arguments: Any = raw_action.get("arguments")
    if arguments is None and "input" in raw_action:
        arguments = raw_action.get("input")

    function = raw_action.get("function")
    if isinstance(function, dict):
        tool = function.get("name") or tool
        arguments = function.get("arguments", arguments)

    if isinstance(arguments, str):
        try:
            parsed = loads(arguments, {})
        except ValueError:
            return {"id": action_id, "tool": tool, "error": "invalid_arguments_json"}
        arguments = parsed

    if arguments is None:
        arguments = {
            key: value
            for key, value in raw_action.items()
            if key not in {"id", "call_id", "tool", "name", "action", "type", "function", "input"}
        }
    if not isinstance(arguments, dict):
        return {"id": action_id, "tool": tool, "error": "arguments_not_object"}
    for key in ("reason", "rationale", "why"):
        if key in raw_action and key not in arguments:
            arguments[key] = raw_action[key]
    tool_name = _normalize_space(str(tool or ""))
    if not tool_name:
        return {"id": action_id, "tool": None, "error": "missing_tool"}
    return {
        "id": action_id,
        "tool": tool_name,
        "arguments": arguments,
    }

def _compact_dream_action_request(raw_action: dict[str, Any], index: int) -> dict[str, Any]:
    action = _normalize_dream_action(raw_action, index)
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    compact = {
        "id": action.get("id"),
        "tool": action.get("tool"),
    }
    if action.get("error"):
        compact["error"] = action.get("error")
        return compact
    for key in (
        "memory_id",
        "candidate_id",
        "page_id",
        "target_page_id",
        "source_id",
        "target_id",
        "id",
        "target_id",
        "target_type",
        "reason",
        "rationale",
        "replacement_id",
        "eval_run_id",
    ):
        value = arguments.get(key)
        if value is not None:
            output_key = "memory_id" if key == "id" else key
            if output_key == "memory_id" and compact.get("memory_id"):
                continue
            compact[output_key] = _truncate(str(value), limit=120)
    if action.get("tool") == "memory_decay_stale_pages":
        if arguments.get("limit") is not None:
            compact["limit"] = _bounded_action_limit(arguments.get("limit"), default=20)
        if arguments.get("stale_confidence") is not None:
            compact["stale_confidence"] = _bounded_confidence(arguments.get("stale_confidence"), 0.35)
    return compact

def _dream_action_skip(action_id: str, tool: Any, reason: Any) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "tool": tool,
        "status": "skipped",
        "reason": _truncate(str(reason or "unknown"), limit=160),
    }

def _compact_dream_tombstone_result(action_id: str, result: dict[str, Any]) -> dict[str, Any]:
    replacement = result.get("replacement") if isinstance(result.get("replacement"), dict) else {}
    eval_case = result.get("eval_case") if isinstance(result.get("eval_case"), dict) else {}
    compact = {
        "action_id": action_id,
        "tool": "memory_tombstone",
        "memory_id": result.get("memory_id"),
        "target_type": result.get("target_type"),
        "status": result.get("status"),
        "tombstone_id": result.get("tombstone_id"),
    }
    if replacement.get("id"):
        compact["replacement_id"] = replacement.get("id")
        compact["replacement_type"] = replacement.get("target_type")
    if eval_case.get("id"):
        compact["eval_case_id"] = eval_case.get("id")
        compact["eval_case_status"] = eval_case.get("status")
    return compact

def _compact_dream_decay_result(action_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "tool": "memory_decay_stale_pages",
        "status": "applied",
        "counts": result.get("counts", {}),
        "staled": [
            {
                "page_id": item.get("page_id"),
                "status": item.get("status"),
                "reasons": item.get("reasons", []),
            }
            for item in result.get("staled", [])
            if isinstance(item, dict)
        ][:10],
        "decayed": [
            {
                "page_id": item.get("page_id"),
                "reasons": item.get("reasons", []),
                "confidence": item.get("confidence"),
            }
            for item in result.get("decayed", [])
            if isinstance(item, dict)
        ][:10],
    }


def _compact_dream_proposal_result(action_id: str, tool: str, proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "tool": tool,
        "status": "pending",
        "decision": "proposal_pending",
        "proposal_id": proposal.get("id"),
        "title": proposal.get("title"),
        "risk": proposal.get("risk"),
        "reason": proposal.get("rationale") or "requires operator confirmation",
    }

def _compact_dream_promote_result(action_id: str, result: dict[str, Any]) -> dict[str, Any]:
    page = result.get("page") if isinstance(result.get("page"), dict) else {}
    compact = {
        "action_id": action_id,
        "tool": "memory_promote_candidate",
        "candidate_id": result.get("candidate_id"),
        "status": result.get("status"),
        "decision": result.get("decision"),
    }
    if result.get("reason"):
        compact["reason"] = _truncate(str(result.get("reason")), limit=160)
    if result.get("gate_reason"):
        compact["gate_reason"] = _truncate(str(result.get("gate_reason")), limit=160)
    if result.get("page_id"):
        compact["page_id"] = result.get("page_id")
    if result.get("page_action"):
        compact["page_action"] = result.get("page_action")
    if page.get("title"):
        compact["page_title"] = page.get("title")
    if result.get("conflict_page_id"):
        compact["conflict_page_id"] = result.get("conflict_page_id")
    if result.get("quality"):
        compact["quality"] = result.get("quality")
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
    if snapshot:
        compact["snapshot_items"] = snapshot.get("page_count", 0)
    return compact

def _compact_dream_reject_result(action_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "tool": "memory_reject_candidate",
        "candidate_id": result.get("candidate_id"),
        "status": result.get("status"),
        "reason": _truncate(str(result.get("reason") or ""), limit=160),
        "tombstone_id": result.get("tombstone_id"),
    }

def _bounded_action_limit(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(100, max(1, parsed))

def _report_completed_at(report: dict[str, Any] | None) -> float | None:
    if not report:
        return None
    completed_at = _float_or_zero(report.get("completed_at"))
    return completed_at or None

def _safe_report_id(report_id: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(report_id or "")).strip("._-")
    return normalized or new_id("dream")
