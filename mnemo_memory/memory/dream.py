from __future__ import annotations

from pathlib import Path
import re
import time
from typing import Any

from ..core.ids import new_id
from ..core.jsonutil import dumps, loads
from .associations import discover_orphan_associations
from .cards import _compact_candidate, _compact_page, _compact_run, _compact_tombstone, _compact_working_note
from ..core.log import get_logger, log_event
from .constants import DREAM_LATEST_FILENAME, DREAM_REPORTS_DIRNAME
from .plans import ACTIVE_PLAN_STATUSES
from .utils import _bounded_confidence, _float_or_zero, _normalize_space, _truncate
from .wiki import materialize_memory_page


_LOG = get_logger("dream")

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
        pending_plan_proposals = [
            _compact_plan_proposal(proposal)
            for proposal in self.store.list_plan_proposals(status="pending", limit=inventory_limit)
        ][:bounded_limit]
        changed_plan_items = [
            _compact_plan_item(item)
            for item in _since_filter(
                self.store.list_plan_items(status=None, limit=inventory_limit, include_archived=True),
                since=since,
                field="updated_at",
            )
        ][:bounded_limit]
        active_goal_context = [
            _compact_plan_item(item)
            for item in self.store.list_plan_items(
                status=[*ACTIVE_PLAN_STATUSES["goal"], *ACTIVE_PLAN_STATUSES["todo"]],
                limit=min(inventory_limit, bounded_limit * 2),
                include_archived=False,
            )
        ][:bounded_limit]
        health = self.health_report(limit=min(10, bounded_limit))
        orphan_ids = [
            card["page_id"]
            for card in health.get("review_cards", [])
            if card.get("kind") == "connect_orphan" and card.get("page_id")
        ]
        association_suggestions = discover_orphan_associations(
            self.store, orphan_ids, limit=bounded_limit
        ) if orphan_ids else []
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
                "association_suggestions": len(association_suggestions),
                "pending_plan_proposals": len(pending_plan_proposals),
                "changed_plan_items": len(changed_plan_items),
                "active_goal_context": len(active_goal_context),
            },
            "note_ids": note_ids,
            "candidate_ids": draft_candidate_ids,
            "w0_pending": notes,
            "memory_candidates": candidates,
            "changed_pages": pages,
            "tombstones": tombstones,
            "recent_runs": recent_runs,
            "association_suggestions": association_suggestions,
            "pending_plan_proposals": pending_plan_proposals,
            "changed_plan_items": changed_plan_items,
            "active_goal_context": active_goal_context,
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
        conflict_candidates = [
            c for c in delta.get("memory_candidates", [])
            if str(c.get("status") or "").startswith("needs_review:conflict")
        ]
        if conflict_candidates:
            focus.append({
                "kind": "resolve_conflicts",
                "count": len(conflict_candidates),
                "tool": "memory_reconcile_conflict",
                "candidates": [
                    {"candidate_id": c["id"], "claim": c.get("claim", "")[:120]}
                    for c in conflict_candidates[:5]
                ],
            })
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
        if counts.get("association_suggestions"):
            focus.append({
                "kind": "connect_orphans",
                "count": counts["association_suggestions"],
                "tool": "memory_link_pages",
            })
        if counts.get("tombstones"):
            focus.append({"kind": "respect_tombstones", "count": counts["tombstones"], "tool": "memory_search"})
        if counts.get("pending_plan_proposals"):
            focus.append(
                {
                    "kind": "review_goal_proposals",
                    "count": counts["pending_plan_proposals"],
                    "tool": "goal_apply_proposal",
                }
            )
        if counts.get("changed_plan_items"):
            focus.append(
                {
                    "kind": "maintain_changed_goals",
                    "count": counts["changed_plan_items"],
                    "tool": "goal_update",
                }
            )
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
            "goal_apply_proposal",
            "goal_reject_proposal",
            "goal_create",
            "goal_update",
            "goal_complete",
            "goal_cancel",
            "goal_archive",
        ]
        if advanced_dreaming:
            allowed_tools.extend(sorted(ADVANCED_DREAM_TOOLS))
        instructions = [
            "Choose 0..N maintenance actions from the delta; do not process the whole store.",
            "Stable memory changes happen only when the model selects an explicit maintenance tool.",
            "Prefer evidence-backed memory candidates, user corrections, conflicts, and tombstones.",
            "User-provided private profile/contact facts may be promoted when they are stable and useful; do not reject solely because they are private.",
            "Reject or forget private content only when the user asked not to save it, asked to delete it, or the source is unsafe/untrusted.",
            "Goal tools are full-auto: they may directly accept/reject goal proposals or create/update/complete/cancel/archive plan_items.",
            "Use the exact user scope from the delta for goal actions; never modify one user's goals based on another user's evidence.",
            "For every goal action include a concise reason explaining the decision.",
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
            "tool_argument_schemas": _dream_tool_argument_schemas(),
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
        deterministic_fallback: bool = False,
        model_calls: int | None = None,
        conflict_resolver: Any | None = None,
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
        execution_mode = "model_required"
        action_execution = None
        if dream_actions:
            action_execution = self.apply_dream_actions(
                dream_actions,
                limit=limit,
                min_confidence=min_confidence,
                report_id=report_id,
                advanced_dreaming=advanced_dreaming,
                execution_policy=execution_policy,
            )
            execution_mode = "model_actions"
            # Model-first + deterministic fallback: let the model reconcile each
            # parked conflict (disambiguate / merge); anything it can't handle
            # falls back to the deterministic rule so nothing stalls for a human.
            conflict_resolved = self._auto_resolve_pending_conflicts(limit, resolver=conflict_resolver)
            if conflict_resolved:
                action_execution = _merge_conflict_resolutions(action_execution, conflict_resolved)
        elif deterministic_fallback:
            consolidation = self.dream_consolidate(
                limit=limit,
                min_confidence=min_confidence,
                candidate_ids=set(delta.get("candidate_ids", [])),
                note_ids=set(delta.get("note_ids", [])),
            )
            # Auto-link discovered associations for orphan pages
            auto_links: list[dict[str, Any]] = []
            for suggestion in delta.get("association_suggestions", []):
                if suggestion.get("weight", 0) >= 0.5:
                    try:
                        link_result = self._apply_dream_link_action(
                            f"auto_link_{suggestion['source_id']}_{suggestion['target_id']}",
                            {
                                "source_id": suggestion["source_id"],
                                "target_id": suggestion["target_id"],
                                "relation": suggestion.get("relation", "discovered_association"),
                                "weight": suggestion.get("weight", 0.5),
                            },
                        )
                        link_result["reason"] = suggestion.get("reason", "keyword_overlap")
                        auto_links.append(link_result)
                    except (ValueError, KeyError):
                        continue
            action_execution = _consolidation_as_action_result(consolidation, auto_links=auto_links)
            execution_mode = "deterministic_fallback"
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
            "model_calls": int(model_calls) if model_calls is not None else None,
            "delta": delta,
            "plan": dream_plan,
            "execution": {
                "mode": execution_mode,
                "result": execution,
            },
            "health_after": self.health_report(limit=min(10, max(1, int(limit)))),
        }
        if persist:
            self.save_dream_report(report)
        action_counts = execution["actions"].get("counts", {}) if isinstance(execution.get("actions"), dict) else {}
        log_event(
            _LOG,
            "dream_run",
            report_id=report_id,
            mode=execution_mode,
            requested=action_counts.get("requested"),
            applied=action_counts.get("applied"),
            skipped=action_counts.get("skipped"),
            duration_s=report["duration_s"],
        )
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
                if tool == "goal_apply_proposal":
                    applied.append(self._apply_goal_apply_proposal_action(action_id, arguments))
                    continue
                if tool == "goal_reject_proposal":
                    applied.append(self._apply_goal_reject_proposal_action(action_id, arguments))
                    continue
                if tool == "goal_create":
                    applied.append(self._apply_goal_create_action(action_id, arguments, report_id=report_id))
                    continue
                if tool == "goal_update":
                    applied.append(self._apply_goal_update_action(action_id, arguments, report_id=report_id))
                    continue
                if tool == "goal_complete":
                    applied.append(self._apply_goal_complete_action(action_id, arguments))
                    continue
                if tool == "goal_cancel":
                    applied.append(self._apply_goal_cancel_action(action_id, arguments))
                    continue
                if tool == "goal_archive":
                    applied.append(self._apply_goal_archive_action(action_id, arguments))
                    continue
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

    def _apply_goal_apply_proposal_action(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        proposal_id = _goal_action_proposal_id(arguments)
        reason = _goal_action_reason(arguments) or "accepted_by_dream"
        result = self.apply_plan_proposal(proposal_id, reason=reason)
        return _compact_goal_proposal_result(action_id, "goal_apply_proposal", result, decision="accepted", reason=reason)

    def _apply_goal_reject_proposal_action(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        proposal_id = _goal_action_proposal_id(arguments)
        reason = _goal_action_reason(arguments)
        if not reason:
            raise ValueError("missing reason")
        result = self.reject_plan_proposal(proposal_id, reason=reason)
        return _compact_goal_proposal_result(action_id, "goal_reject_proposal", result, decision="rejected", reason=reason)

    def _apply_goal_create_action(
        self,
        action_id: str,
        arguments: dict[str, Any],
        *,
        report_id: str | None,
    ) -> dict[str, Any]:
        title = _normalize_space(str(arguments.get("title") or arguments.get("goal") or arguments.get("task") or ""))
        if not title:
            raise ValueError("missing title")
        result = self.create_plan_item(
            kind=_goal_action_kind(arguments),
            title=title,
            detail=_normalize_space(str(arguments.get("detail") or arguments.get("description") or "")),
            scope=_goal_action_scope(arguments),
            parent_id=_optional_goal_text(arguments.get("parent_id")),
            status=_optional_goal_text(arguments.get("status")),
            priority=_goal_action_priority(arguments),
            due_at=arguments.get("due_at"),
            source="dream",
            source_event_id=_optional_goal_text(arguments.get("source_event_id")),
            metadata=_goal_action_metadata(action_id, arguments, report_id=report_id),
        )
        return _compact_goal_item_result(action_id, "goal_create", result, reason=_goal_action_reason(arguments))

    def _apply_goal_update_action(
        self,
        action_id: str,
        arguments: dict[str, Any],
        *,
        report_id: str | None,
    ) -> dict[str, Any]:
        item_id = _goal_action_item_id(arguments)
        existing = self.store.get_plan_item(item_id)
        if not existing:
            raise ValueError(f"plan item not found: {item_id}")
        fields: dict[str, Any] = {}
        for arg_key, field_key in (
            ("kind", "kind"),
            ("parent_id", "parent_id"),
            ("title", "title"),
            ("detail", "detail"),
            ("description", "detail"),
            ("status", "status"),
            ("priority", "priority"),
            ("due_at", "due_at"),
        ):
            if arg_key in arguments:
                fields[field_key] = arguments.get(arg_key)
        if "uid" in arguments or "user_id" in arguments or "scope" in arguments:
            fields["scope"] = _goal_action_scope(arguments, default=str(existing.get("scope") or "global"))
        fields["metadata"] = _goal_action_metadata(
            action_id,
            arguments,
            report_id=report_id,
            existing=existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {},
        )
        result = self.update_plan_item(item_id, **fields)
        return _compact_goal_item_result(action_id, "goal_update", result, reason=_goal_action_reason(arguments))

    def _apply_goal_complete_action(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        item_id = _goal_action_item_id(arguments)
        result = self.complete_plan_item(item_id)
        return _compact_goal_item_result(action_id, "goal_complete", result, reason=_goal_action_reason(arguments))

    def _apply_goal_cancel_action(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        item_id = _goal_action_item_id(arguments)
        reason = _goal_action_reason(arguments) or "cancelled_by_dream"
        result = self.cancel_plan_item(item_id, reason=reason)
        return _compact_goal_item_result(action_id, "goal_cancel", result, reason=reason)

    def _apply_goal_archive_action(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        item_id = _goal_action_item_id(arguments)
        result = self.archive_plan_item(item_id)
        return _compact_goal_item_result(action_id, "goal_archive", result, reason=_goal_action_reason(arguments))

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
        self._snapshot_page_before_mutation(page, change_reason="dream_rewrite", changed_by="dream")
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
        self._snapshot_page_before_mutation(target, change_reason="dream_merge", changed_by="dream")
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

def _compact_plan_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "title": _truncate(str(item.get("title") or ""), limit=160),
        "detail": _truncate(str(item.get("detail") or ""), limit=240),
        "scope": item.get("scope"),
        "status": item.get("status"),
        "priority": item.get("priority"),
        "due_at": item.get("due_at"),
        "parent_id": item.get("parent_id"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "completed_at": item.get("completed_at"),
    }


def _compact_plan_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": proposal.get("id"),
        "kind": proposal.get("kind"),
        "action": proposal.get("action"),
        "target_id": proposal.get("target_id"),
        "title": _truncate(str(proposal.get("title") or ""), limit=160),
        "detail": _truncate(str(proposal.get("detail") or ""), limit=240),
        "scope": proposal.get("scope"),
        "status": proposal.get("status"),
        "priority": proposal.get("priority"),
        "due_at": proposal.get("due_at"),
        "confidence": proposal.get("confidence"),
        "reason": _truncate(str(proposal.get("reason") or ""), limit=240),
        "source_event_id": proposal.get("source_event_id"),
        "proposal_status": proposal.get("proposal_status"),
        "created_at": proposal.get("created_at"),
    }


def _dream_tool_argument_schemas() -> dict[str, Any]:
    return {
        "goal_apply_proposal": {"proposal_id": "required plprop id", "reason": "required concise acceptance reason"},
        "goal_reject_proposal": {"proposal_id": "required plprop id", "reason": "required concise rejection reason"},
        "goal_create": {
            "title": "required goal title",
            "detail": "optional details",
            "uid": "optional user id; preferred when scope is user scoped",
            "scope": "optional exact scope from delta",
            "status": "active|paused for goals, or open|doing for todos",
            "priority": "low|normal|high",
            "due_at": "optional unix timestamp",
            "reason": "required concise creation reason",
        },
        "goal_update": {
            "goal_id": "required plan item id",
            "title": "optional replacement title",
            "detail": "optional replacement detail",
            "status": "optional valid goal/todo status",
            "priority": "optional low|normal|high",
            "due_at": "optional unix timestamp or null",
            "reason": "required concise update reason",
        },
        "goal_complete": {"goal_id": "required plan item id", "reason": "required concise completion reason"},
        "goal_cancel": {"goal_id": "required plan item id", "reason": "required concise cancellation reason"},
        "goal_archive": {"goal_id": "required plan item id", "reason": "required concise archival reason"},
    }


def _goal_action_item_id(arguments: dict[str, Any]) -> str:
    item_id = _normalize_space(
        str(
            arguments.get("goal_id")
            or arguments.get("plan_id")
            or arguments.get("item_id")
            or arguments.get("target_id")
            or arguments.get("id")
            or ""
        )
    )
    if not item_id:
        raise ValueError("missing goal_id")
    return item_id


def _goal_action_proposal_id(arguments: dict[str, Any]) -> str:
    proposal_id = _normalize_space(
        str(arguments.get("proposal_id") or arguments.get("plan_proposal_id") or arguments.get("id") or "")
    )
    if not proposal_id:
        raise ValueError("missing proposal_id")
    return proposal_id


def _goal_action_reason(arguments: dict[str, Any]) -> str:
    return _normalize_space(str(arguments.get("reason") or arguments.get("rationale") or arguments.get("why") or ""))


def _goal_action_kind(arguments: dict[str, Any]) -> str:
    kind = _normalize_space(str(arguments.get("kind") or "goal")).casefold()
    return kind if kind in {"goal", "todo"} else "goal"


def _goal_action_priority(arguments: dict[str, Any]) -> str:
    priority = _normalize_space(str(arguments.get("priority") or "normal")).casefold()
    return priority if priority in {"low", "normal", "high"} else "normal"


def _goal_action_scope(arguments: dict[str, Any], *, default: str = "global") -> str:
    uid = _normalize_space(str(arguments.get("uid") or arguments.get("user_id") or ""))
    if uid:
        return uid if uid.casefold().startswith("user:") else f"user:{uid}"
    return _normalize_space(str(arguments.get("scope") or default)) or "global"


def _goal_action_metadata(
    action_id: str,
    arguments: dict[str, Any],
    *,
    report_id: str | None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(existing or {})
    provided = arguments.get("metadata") if isinstance(arguments.get("metadata"), dict) else {}
    metadata.update(provided)
    metadata["dream_action_id"] = action_id
    metadata["dream_maintained"] = True
    if report_id:
        metadata["dream_report_id"] = report_id
    reason = _goal_action_reason(arguments)
    if reason:
        metadata["dream_reason"] = reason
    return metadata


def _optional_goal_text(value: Any) -> str | None:
    text = _normalize_space(str(value or ""))
    return text or None


def _compact_goal_item_result(
    action_id: str,
    tool: str,
    result: dict[str, Any],
    *,
    reason: str = "",
) -> dict[str, Any]:
    item = result.get("item") if isinstance(result.get("item"), dict) else {}
    compact = {
        "action_id": action_id,
        "tool": tool,
        "status": "applied",
        "decision": tool.replace("goal_", ""),
        "goal_id": item.get("id"),
        "kind": item.get("kind"),
        "title": item.get("title"),
        "goal_status": item.get("status"),
        "scope": item.get("scope"),
    }
    clean_reason = _normalize_space(str(reason or ""))
    if clean_reason:
        compact["reason"] = _truncate(clean_reason, limit=160)
    return compact


def _compact_goal_proposal_result(
    action_id: str,
    tool: str,
    result: dict[str, Any],
    *,
    decision: str,
    reason: str = "",
) -> dict[str, Any]:
    proposal = result.get("proposal") if isinstance(result.get("proposal"), dict) else {}
    item = result.get("result", {}).get("item") if isinstance(result.get("result"), dict) else None
    compact = {
        "action_id": action_id,
        "tool": tool,
        "status": "applied",
        "decision": decision,
        "proposal_id": result.get("proposal_id") or proposal.get("id"),
        "proposal_status": proposal.get("proposal_status"),
        "title": proposal.get("title"),
        "scope": proposal.get("scope"),
    }
    if isinstance(item, dict):
        compact["goal_id"] = item.get("id")
        compact["goal_status"] = item.get("status")
    clean_reason = _normalize_space(str(reason or proposal.get("decision_reason") or ""))
    if clean_reason:
        compact["reason"] = _truncate(clean_reason, limit=160)
    return compact


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
        "model_calls": report.get("model_calls"),
        "delta_counts": delta.get("counts", {}),
        "execution": {
            "mode": execution.get("mode"),
            "model_calls": report.get("model_calls"),
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
        "proposal_id",
        "goal_id",
        "plan_id",
        "item_id",
        "page_id",
        "target_page_id",
        "source_id",
        "target_id",
        "id",
        "target_id",
        "target_type",
        "reason",
        "rationale",
        "title",
        "status",
        "uid",
        "scope",
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


def _merge_conflict_resolutions(
    action_execution: dict[str, Any] | None,
    resolved: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fold deterministic conflict resolutions into a model action result so they
    show up in the report (and decision log) alongside the model's own actions."""
    base = dict(action_execution or {"kind": "dream_memory_action_result", "applied": [], "skipped": [], "counts": {}})
    applied = list(base.get("applied") or [])
    for item in resolved:
        keep_old = item.get("resolution") == "keep_old"
        applied.append({
            "action_id": f"auto_conflict_{item.get('candidate_id', '')}",
            "tool": "memory_reject_candidate" if keep_old else "memory_promote_candidate",
            "candidate_id": item.get("candidate_id"),
            "page_id": item.get("page_id"),
            "status": item.get("status") if keep_old else "promoted",
            "decision": "conflict_resolved",
            "reason": item.get("reason") or f"conflict_resolved:{item.get('resolution')}",
        })
    counts = dict(base.get("counts") or {})
    counts["applied"] = len(applied)
    base["applied"] = applied
    base["counts"] = counts
    return base


def _consolidation_as_action_result(
    consolidation: dict[str, Any],
    *,
    auto_links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    promoted = consolidation.get("promoted", [])
    rejected = consolidation.get("rejected", [])
    skipped = consolidation.get("skipped", [])
    conflicts = consolidation.get("conflicts", [])
    applied: list[dict[str, Any]] = []
    for item in promoted:
        applied.append({
            "action_id": f"auto_promote_{item.get('candidate_id', '')}",
            "tool": "memory_promote_candidate",
            "candidate_id": item.get("candidate_id"),
            "status": "promoted",
            "decision": "promoted",
            "page_id": item.get("page_id"),
            "page_action": item.get("page_action"),
            "reason": item.get("reason") or "deterministic_fallback",
        })
    for item in rejected:
        applied.append({
            "action_id": f"auto_reject_{item.get('candidate_id', '')}",
            "tool": "memory_reject_candidate",
            "candidate_id": item.get("candidate_id"),
            "status": item.get("status"),
            "reason": item.get("reason") or "deterministic_fallback",
        })
    skipped_items: list[dict[str, Any]] = []
    for item in [*skipped, *conflicts]:
        skipped_items.append({
            "action_id": f"auto_skip_{item.get('candidate_id', '')}",
            "tool": "memory_promote_candidate",
            "status": "skipped",
            "reason": item.get("reason") or item.get("status") or "deterministic_fallback",
        })
    w0 = consolidation.get("w0", {})
    w0_applied = [
        {
            "action_id": f"auto_ingest_{item.get('note_id', '')}",
            "tool": "memory_write_candidate",
            "status": "candidate_created",
            "note_id": item.get("note_id"),
            "candidate_id": item.get("candidate_id"),
        }
        for item in w0.get("created", [])
    ]
    all_applied = [*w0_applied, *applied, *(auto_links or [])]
    return {
        "kind": "dream_memory_action_result",
        "mode": "deterministic_fallback",
        "counts": {
            "requested": len(all_applied) + len(skipped_items),
            "applied": len(all_applied),
            "skipped": len(skipped_items),
        },
        "applied": all_applied,
        "skipped": skipped_items,
    }
