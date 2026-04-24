from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..core.errors import NotFoundError
from ..storage import StateStore


VALID_RISKS = {"read", "write", "external", "admin"}
RISK_RANK = {"read": 0, "write": 1, "external": 2, "admin": 3}


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

    def install_candidate(self, candidate_id: str, *, available_tools: Mapping[str, Any]) -> dict[str, Any]:
        candidate = self.store.get_tool_candidate(candidate_id)
        if not candidate:
            raise NotFoundError(f"tool candidate not found: {candidate_id}")

        if candidate["status"] != "ready":
            status = "blocked:not_ready"
            self.store.update_tool_candidate_status(candidate_id, status)
            return {
                "candidate_id": candidate_id,
                "name": candidate["name"],
                "status": status,
                "installed": False,
                "errors": [f"candidate must be ready before install; current status is {candidate['status']}"],
            }

        errors = validate_candidate_spec(candidate)
        implementation_errors = validate_alias_implementation(candidate, available_tools)
        errors.extend(implementation_errors)
        if errors:
            status = "blocked:install_invalid"
            self.store.update_tool_candidate_status(candidate_id, status)
            return {
                "candidate_id": candidate_id,
                "name": candidate["name"],
                "status": status,
                "installed": False,
                "errors": errors,
            }

        spec = candidate["spec"]
        implementation = spec["implementation"]
        tool_id = self.store.upsert_generated_tool(
            candidate_id=candidate_id,
            name=candidate["name"],
            description=spec["description"],
            risk=spec["risk"],
            input_schema=spec["input_schema"],
            implementation=implementation,
            status="active",
        )
        self.store.update_tool_candidate_status(candidate_id, "installed")
        return {
            "candidate_id": candidate_id,
            "tool_id": tool_id,
            "name": candidate["name"],
            "status": "installed",
            "generated_tool_status": "active",
            "installed": True,
            "target_tool": implementation["target_tool"],
        }

    def uninstall_generated_tool(self, name: str) -> dict[str, Any]:
        tool = self.store.get_generated_tool(name)
        if not tool:
            raise NotFoundError(f"generated tool not found: {name}")
        self.store.update_generated_tool_status(name, "disabled")
        candidate_id = tool.get("candidate_id")
        if candidate_id:
            self.store.update_tool_candidate_status(str(candidate_id), "ready")
        return {
            "name": name,
            "status": "disabled",
            "candidate_id": candidate_id,
            "installed": False,
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


def validate_alias_implementation(candidate: dict[str, Any], available_tools: Mapping[str, Any]) -> list[str]:
    spec = candidate.get("spec") or {}
    implementation = spec.get("implementation")
    errors: list[str] = []
    if not isinstance(implementation, dict):
        return ["implementation must be an alias object"]
    if implementation.get("type") != "alias":
        errors.append("implementation.type must be alias")
    target_tool = implementation.get("target_tool")
    if not isinstance(target_tool, str) or not target_tool.strip():
        errors.append("implementation.target_tool is required")
        return errors
    target_tool = target_tool.strip()
    candidate_name = candidate.get("name")
    if isinstance(candidate_name, str) and candidate_name in available_tools:
        errors.append(f"generated tool name conflicts with existing tool: {candidate_name}")
    if target_tool == candidate.get("name"):
        errors.append("generated tool cannot alias itself")
    target_spec = available_tools.get(target_tool)
    if not target_spec:
        errors.append(f"target tool is not available: {target_tool}")
    else:
        candidate_risk = (candidate.get("spec") or {}).get("risk")
        target_risk = _tool_risk(target_spec)
        if isinstance(candidate_risk, str) and isinstance(target_risk, str):
            if RISK_RANK.get(candidate_risk, -1) < RISK_RANK.get(target_risk, 99):
                errors.append("generated tool risk cannot be lower than target tool risk")
    argument_map = implementation.get("argument_map", {})
    if argument_map is not None and not isinstance(argument_map, dict):
        errors.append("implementation.argument_map must be an object")
    return errors


def _tool_risk(spec: Any) -> str | None:
    if isinstance(spec, dict):
        value = spec.get("risk")
    else:
        value = getattr(spec, "risk", None)
    return value if isinstance(value, str) else None
