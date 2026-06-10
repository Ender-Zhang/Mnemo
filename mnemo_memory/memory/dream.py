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
            "mode": "model_led_tool_use",
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
                "memory_promote_candidate",
                "memory_reject_candidate",
                "learning_discard",
            ],
            "focus_candidates": focus,
            "instructions": [
                "Choose 0..N maintenance actions from the delta; do not process the whole store.",
                "Stable memory changes happen only when the model selects an explicit maintenance tool.",
                "Prefer evidence-backed memory candidates, user corrections, conflicts, and tombstones.",
                "Skip low-value items with a reason instead of forcing a workflow step.",
            ],
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
    ) -> dict[str, Any]:
        started_at = time.time()
        if since is None:
            latest = self.load_latest_dream_report()
            since = _report_completed_at(latest)
        delta = self.collect_dream_delta(limit=limit, since=since)
        dream_plan = self.build_dream_plan(delta, limit=limit)
        dream_actions = _dream_actions_from_inputs(actions=actions, plan=plan)
        if dream_actions:
            dream_plan["proposed_actions"] = [
                _compact_dream_action_request(action, index)
                for index, action in enumerate(dream_actions[: max(1, int(limit))])
            ]
        action_execution = (
            self.apply_dream_actions(dream_actions, limit=limit, min_confidence=min_confidence)
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
            "id": new_id("dream"),
            "started_at": started_at,
            "completed_at": completed_at,
            "since": since,
            "duration_s": round(completed_at - started_at, 3),
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
    ) -> dict[str, Any]:
        bounded_limit = max(0, int(limit))
        requested = list(actions or [])[:bounded_limit]
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

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


def _since_filter(items: list[dict[str, Any]], *, since: float | None, field: str) -> list[dict[str, Any]]:
    if since is None:
        return items
    return [
        item
        for item in items
        if _float_or_zero(item.get(field)) > since
    ]

def _compact_dream_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    execution = report.get("execution") if isinstance(report.get("execution"), dict) else {}
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    delta = report.get("delta") if isinstance(report.get("delta"), dict) else {}
    actions = result.get("actions") if isinstance(result.get("actions"), dict) else {}
    action_counts = actions.get("counts") if isinstance(actions.get("counts"), dict) else {}
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    review_results = _dream_review_results(actions.get("applied"))
    reject_reasons = _dream_reject_reasons(actions.get("applied"))
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
            "rejected": len(result.get("rejected", [])) or len(reject_reasons),
            "skipped": len(result.get("skipped", [])),
            "conflicts": len(result.get("conflicts", [])),
            "actions_applied": action_counts.get("applied", 0),
            "actions_skipped": action_counts.get("skipped", 0),
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
        "id",
        "target_id",
        "target_type",
        "reason",
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
