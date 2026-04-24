from __future__ import annotations

from typing import Any

from ..core.errors import NotFoundError
from ..storage import StateStore


VALID_RISKS = {"read", "write", "external", "admin"}


class ToolEvolutionService:
    def __init__(self, store: StateStore):
        self.store = store

    def review_candidate(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.store.get_tool_candidate(candidate_id)
        if not candidate:
            raise NotFoundError(f"tool candidate not found: {candidate_id}")

        errors = validate_candidate_spec(candidate)
        passed_cases = self.store.list_eval_cases(status="passed", tool_name=candidate["name"], limit=100)
        if errors:
            status = "blocked:invalid_spec"
        elif not passed_cases:
            status = "blocked:missing_eval"
        else:
            status = "ready"

        self.store.update_tool_candidate_status(candidate_id, status)
        return {
            "candidate_id": candidate_id,
            "name": candidate["name"],
            "status": status,
            "valid": not errors,
            "errors": errors,
            "passed_eval_case_ids": [case["id"] for case in passed_cases],
        }


def validate_candidate_spec(candidate: dict[str, Any]) -> list[str]:
    spec = candidate.get("spec") or {}
    errors: list[str] = []
    spec_name = spec.get("name") or candidate.get("name")
    if not isinstance(spec_name, str) or not spec_name.strip():
        errors.append("missing name")
    if spec_name and spec_name != candidate.get("name"):
        errors.append("spec name must match candidate name")
    if not isinstance(spec.get("description"), str) or not spec["description"].strip():
        errors.append("missing description")
    if spec.get("risk") not in VALID_RISKS:
        errors.append("risk must be one of read/write/external/admin")
    input_schema = spec.get("input_schema")
    if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
        errors.append("input_schema must be an object schema")
    return errors
