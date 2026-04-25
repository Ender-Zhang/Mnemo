from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from ..storage import StateStore
from .filesystem import SkillFile, load_skill_metadata, scan_skill_files


_WORKSPACE_SKILL_ROOTS = (
    (".mnemo", "skills"),
    (".agents", "skills"),
    (".claude", "skills"),
    (".hermes", "skills"),
    (".openclaw", "skills"),
)
_HOME_SKILL_ROOTS = (
    (".claude", "skills"),
    (".hermes", "skills"),
    (".openclaw", "skills"),
)


class SkillService:
    def __init__(self, store: StateStore, roots: list[str | Path] | None = None):
        self.store = store
        self.roots = [Path(root).expanduser() for root in roots or []]

    def scan(self) -> list[dict[str, Any]]:
        scanned = scan_skill_files(self.roots)
        for skill in scanned:
            self.store.upsert_skill(
                skill.name,
                skill.description,
                skill.body,
                source=f"file:{skill.path}",
                status="active",
                path=str(skill.path),
            )
        return [_skill_file_as_dict(skill) for skill in scanned]

    def list(self) -> list[dict[str, Any]]:
        return self.store.list_skills()

    def context_cards(self, limit: int = 12) -> list[dict[str, Any]]:
        skills = self.store.list_skills()
        usage_stats = _skill_usage_stats(self.store)
        ranked = sorted(skills, key=lambda skill: _skill_rank(skill, usage_stats))
        return [_skill_context_card(skill, usage_stats.get(skill["name"])) for skill in ranked[:limit]]

    def view(self, name: str) -> dict[str, Any] | None:
        return self.store.get_skill(name)

    def run_eval_case(self, case_id: str) -> dict[str, Any]:
        eval_case = self.store.get_eval_case(case_id)
        if not eval_case:
            raise ValueError(f"Eval case not found: {case_id}")

        case = eval_case.get("case") or {}
        skill_name = _eval_case_skill_name(case)
        assertions: list[dict[str, Any]] = []
        errors: list[str] = []
        skill = self.store.get_skill(skill_name) if skill_name else None
        if not skill_name:
            errors.append("missing_skill_target")
        elif not skill:
            errors.append("skill_not_found")
        else:
            assertions, errors = _run_skill_assertions(skill, case)

        passed = not errors
        status = "passed" if passed else "failed"
        result = {
            "ok": passed,
            "skill_name": skill_name,
            "errors": errors,
            "assertions": assertions,
        }
        self.store.update_eval_case_status(case_id, status, result=result)
        return {
            "case_id": case_id,
            "skill_name": skill_name,
            "status": status,
            "passed": passed,
            "errors": errors,
            "assertions": assertions,
        }

    def crystallize_from_run(
        self,
        run_id: str,
        name: str,
        *,
        description: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        trace = self.store.get_run_events(run_id)
        if not trace:
            raise ValueError(f"Run not found: {run_id}")
        if not _run_completed(trace):
            raise ValueError(f"Run is not completed: {run_id}")

        tool_results = _compact_successful_tool_results(trace)
        if not tool_results:
            raise ValueError(f"Run has no successful tool results: {run_id}")

        skill_name = name.strip()
        if not skill_name:
            raise ValueError("Skill name is required")
        skill_description = (description or f"Crystallized SOP from run {run_id}").strip()
        body = _crystallized_skill_body(
            run_id=run_id,
            name=skill_name,
            description=skill_description,
            tool_results=tool_results,
            notes=notes,
        )
        skill_id = self.store.upsert_skill(
            skill_name,
            skill_description,
            body,
            source=f"run:{run_id}:crystallized",
            status="draft",
        )
        return {
            "skill_id": skill_id,
            "name": skill_name,
            "description": skill_description,
            "status": "draft",
            "source_run_id": run_id,
            "tool_names": _unique_tool_names(tool_results),
        }

    def review(self, name: str) -> dict[str, Any]:
        skill = self.store.get_skill(name)
        if not skill:
            raise ValueError(f"Skill not found: {name}")

        usage = _skill_usage_stats(self.store).get(name, {})
        eval_cases = self.store.list_eval_cases(skill_name=name, limit=100)
        eval_summary = _skill_eval_summary(eval_cases)
        if skill.get("status") == "active":
            return {
                "name": name,
                "status": "active",
                "errors": [],
                "usage": _compact_usage(usage),
                "evals": eval_summary,
                "reason": "already_active",
            }

        errors = _skill_review_errors(skill, usage)
        errors.extend(_skill_eval_errors(eval_summary))
        errors = list(dict.fromkeys(errors))
        status = "ready" if not errors else f"blocked:{errors[0]}"
        self.store.update_skill_status(name, status)
        return {
            "name": name,
            "status": status,
            "errors": errors,
            "usage": _compact_usage(usage),
            "evals": eval_summary,
        }

    def promote(self, name: str) -> dict[str, Any]:
        skill = self.store.get_skill(name)
        if not skill:
            raise ValueError(f"Skill not found: {name}")

        target_dir = self.store.state_dir / "skills" / "_generated" / _slug(name)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "SKILL.md"
        target_path.write_text(_skill_markdown(skill), encoding="utf-8")
        self.store.update_skill_status(name, "active", source="generated", path=str(target_path))
        promoted = self.store.get_skill(name) or skill
        return {
            "name": name,
            "path": str(target_path),
            "skill": promoted,
        }


def default_skill_roots(
    state_dir: str | Path,
    workspace: str | Path | None = None,
    home: str | Path | None = None,
) -> list[Path]:
    workspace_path = Path(workspace or Path.cwd()).expanduser()
    state_path = Path(state_dir).expanduser()
    home_path = Path.home().expanduser() if home is None else Path(home).expanduser()
    roots = [state_path / "skills"]
    roots.extend(workspace_path.joinpath(*parts) for parts in _WORKSPACE_SKILL_ROOTS)
    roots.extend(home_path.joinpath(*parts) for parts in _HOME_SKILL_ROOTS)
    return _dedupe_paths(roots)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _path_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve(strict=False))
    except OSError:
        return str(path.expanduser())


def _skill_file_as_dict(skill: SkillFile) -> dict[str, Any]:
    return {
        "name": skill.name,
        "description": skill.description,
        "body": skill.body,
        "path": str(skill.path),
        "source_root": str(skill.source_root),
        "metadata": skill.metadata,
    }


def _skill_context_card(skill: dict[str, Any], usage: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = _skill_metadata(skill)
    card = {
        "name": skill["name"],
        "description": skill.get("description", ""),
        "status": skill.get("status", "unknown"),
        "source": skill.get("source", ""),
        "path": skill.get("path"),
    }

    allowed_tools = _metadata_allowed_tools(metadata)
    if allowed_tools:
        card["allowed_tools"] = allowed_tools

    for key in ("arguments", "scope"):
        if key in metadata:
            card[key] = metadata[key]

    if not card.get("source") and "source" in metadata:
        card["source"] = metadata["source"]
    if not card.get("path") and "path" in metadata:
        card["path"] = metadata["path"]

    if usage:
        card["usage"] = {
            "uses": usage.get("uses", 0),
            "views": usage.get("views", 0),
            "outcomes": usage.get("outcomes", 0),
            "successes": usage.get("successes", 0),
            "failures": usage.get("failures", 0),
            "avg_score": round(float(usage.get("avg_score", 0.0)), 3),
        }

    return card


def _skill_usage_stats(store: StateStore) -> dict[str, dict[str, Any]]:
    stats = getattr(store, "skill_usage_stats", None)
    if not stats:
        return {}
    return stats()


def _skill_rank(skill: dict[str, Any], stats: dict[str, dict[str, Any]]) -> tuple[float, int, int, str]:
    usage = stats.get(skill["name"], {})
    return (
        -float(usage.get("avg_score", 0.0)),
        -int(usage.get("successes", 0)),
        -int(usage.get("uses", 0)),
        str(skill["name"]),
    )


def _skill_review_errors(skill: dict[str, Any], usage: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    name = str(skill.get("name") or "").strip()
    description = str(skill.get("description") or "").strip()
    body = str(skill.get("body") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", name):
        errors.append("invalid_name")
    if len(description) < 8:
        errors.append("missing_description")
    if len(body) < 20:
        errors.append("body_too_short")
    if int(usage.get("outcomes", 0)) > 0 and float(usage.get("avg_score", 0.0)) < 0:
        errors.append("negative_usage")
    if int(usage.get("failures", 0)) > int(usage.get("successes", 0)) and int(usage.get("successes", 0)) == 0:
        errors.append("negative_usage")
    return list(dict.fromkeys(errors))


def _eval_case_skill_name(case: dict[str, Any]) -> str:
    for key in ("skill_name", "skill_candidate", "skill", "name"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _run_skill_assertions(skill: dict[str, Any], case: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    body = str(skill.get("body") or "")
    description = str(skill.get("description") or "")
    assertions: list[dict[str, Any]] = []
    errors: list[str] = []
    payload = _assertion_payload(case)

    for expected in _string_list(payload.get("body_contains")):
        passed = expected in body
        assertions.append({"name": "body_contains", "value": expected, "passed": passed})
        if not passed:
            errors.append("body_missing_text")

    for expected in _string_list(payload.get("description_contains")):
        passed = expected in description
        assertions.append({"name": "description_contains", "value": expected, "passed": passed})
        if not passed:
            errors.append("description_missing_text")

    for forbidden in [*_string_list(payload.get("body_not_contains")), *_string_list(payload.get("body_forbids"))]:
        passed = forbidden not in body
        assertions.append({"name": "body_not_contains", "value": forbidden, "passed": passed})
        if not passed:
            errors.append("body_forbidden_text")

    min_chars = payload.get("min_body_chars")
    if min_chars is not None:
        try:
            min_value = int(min_chars)
        except (TypeError, ValueError):
            min_value = -1
        passed = min_value >= 0 and len(body.strip()) >= min_value
        assertions.append({"name": "min_body_chars", "value": min_chars, "passed": passed})
        if not passed:
            errors.append("body_too_short")

    return assertions, list(dict.fromkeys(errors))


def _assertion_payload(case: dict[str, Any]) -> dict[str, Any]:
    assertions = case.get("assertions")
    if isinstance(assertions, dict):
        return {**case, **assertions}
    return case


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _skill_eval_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [case["id"] for case in cases if case.get("status") == "passed"]
    failed = [case["id"] for case in cases if case.get("status") == "failed"]
    pending = [case["id"] for case in cases if case.get("status") not in {"passed", "failed"}]
    return {
        "total": len(cases),
        "passed": len(passed),
        "failed": len(failed),
        "pending": len(pending),
        "passed_eval_case_ids": passed,
        "failed_eval_case_ids": failed,
        "pending_eval_case_ids": pending,
    }


def _skill_eval_errors(summary: dict[str, Any]) -> list[str]:
    if int(summary.get("failed", 0)) > 0:
        return ["failed_eval"]
    if int(summary.get("total", 0)) > 0 and int(summary.get("passed", 0)) == 0:
        return ["missing_eval"]
    return []


def _run_completed(trace: list[dict[str, Any]]) -> bool:
    completed = False
    for event in trace:
        if event.get("event_type") != "run.completed":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            completed = True
            continue
        completed = completed or str(payload.get("status") or "completed") == "completed"
    return completed


def _compact_successful_tool_results(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for event in trace:
        if event.get("event_type") != "tool.result":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or not payload.get("ok"):
            continue
        tool_name = str(payload.get("tool_name") or "").strip()
        if not tool_name or tool_name == "skill_crystallize_from_run":
            continue
        results.append(
            {
                "tool_name": tool_name,
                "summary": _compact_text(payload.get("summary") or "Tool call completed.", limit=200),
                "evidence_count": _evidence_count(payload.get("evidence")),
            }
        )
    return results


def _crystallized_skill_body(
    *,
    run_id: str,
    name: str,
    description: str,
    tool_results: list[dict[str, Any]],
    notes: str | None = None,
) -> str:
    tool_names = _unique_tool_names(tool_results)
    lines = [
        "# Purpose",
        description,
        "",
        "# Procedure",
        "1. Start from the user's current goal and relevant mission context.",
    ]
    for index, tool_name in enumerate(tool_names, start=2):
        lines.append(f"{index}. Use `{tool_name}` when the task state calls for the same capability.")
    lines.extend(
        [
            f"{len(tool_names) + 2}. Return concise progress and cite compact evidence, not raw payloads.",
            "",
            "# Source Run Evidence",
            f"- source_run_id: `{run_id}`",
            f"- draft_skill: `{name}`",
            f"- tools: {', '.join(f'`{tool_name}`' for tool_name in tool_names)}",
            "- compact tool summaries:",
        ]
    )
    for result in tool_results:
        lines.append(
            f"  - `{result['tool_name']}`: {result['summary']} "
            f"(evidence_items={result['evidence_count']})"
        )
    lines.extend(
        [
            "",
            "# Review Notes",
            _compact_text(notes, limit=800) if notes else "Review and test this draft before promotion.",
        ]
    )
    return "\n".join(lines).strip()


def _unique_tool_names(tool_results: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for result in tool_results:
        name = str(result.get("tool_name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _evidence_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _compact_text(value: Any, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _compact_usage(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "uses": int(usage.get("uses", 0)),
        "outcomes": int(usage.get("outcomes", 0)),
        "successes": int(usage.get("successes", 0)),
        "failures": int(usage.get("failures", 0)),
        "avg_score": round(float(usage.get("avg_score", 0.0)), 3),
    }


def _skill_metadata(skill: dict[str, Any]) -> dict[str, Any]:
    metadata = skill.get("metadata")
    if isinstance(metadata, dict):
        return metadata

    path = skill.get("path")
    if not path:
        return {}
    return load_skill_metadata(path)


def _metadata_allowed_tools(metadata: dict[str, Any]) -> list[str]:
    value = metadata.get("allowed_tools", metadata.get("allowed-tools", []))
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    if isinstance(value, str) and value:
        return [value]
    return []


def _skill_markdown(skill: dict[str, Any]) -> str:
    return "\n".join(
        [
            "---",
            f"name: {skill['name']}",
            f"description: {skill.get('description', '')}",
            "---",
            "",
            skill.get("body", "").strip(),
            "",
        ]
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or "skill"
