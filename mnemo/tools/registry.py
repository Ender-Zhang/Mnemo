from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, replace
from typing import Any

from ..core.errors import NotFoundError, ToolError
from ..core.models import ToolCallEnvelope, ToolExecutionPolicy, ToolPermission, ToolResult, ToolSpec
from ..memory import MemoryEngine
from ..runtime.ledger import RunLedger
from ..storage import StateStore


ToolHandler = Callable[[dict[str, Any], "ToolContext"], dict[str, Any]]


class ToolContext:
    def __init__(self, *, store: StateStore, ledger: RunLedger, run_id: str, mission_id: str):
        self.store = store
        self.ledger = ledger
        self.run_id = run_id
        self.mission_id = mission_id


def _schema(required: list[str], properties: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


CORE_TOOL_SPECS = [
    ToolSpec(
        name="memory_search",
        description="Search memory candidates and stable memory snippets by semantic query.",
        risk="read",
        input_schema=_schema(
            ["query"],
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
        ),
    ),
    ToolSpec(
        name="memory_read",
        description="Read a specific memory candidate or memory page by id.",
        risk="read",
        input_schema=_schema(["id"], {"id": {"type": "string"}}),
    ),
    ToolSpec(
        name="working_note",
        description="Record a short mission-scoped working note or scratchpad observation.",
        risk="write",
        input_schema=_schema(["content"], {"content": {"type": "string"}}),
    ),
    ToolSpec(
        name="skills_list",
        description="List available skills as compact cards. Full skill content requires skill_view.",
        risk="read",
        input_schema=_schema([], {}),
    ),
    ToolSpec(
        name="skill_view",
        description="Load the full body for one selected skill.",
        risk="read",
        input_schema=_schema(["name"], {"name": {"type": "string"}}),
    ),
    ToolSpec(
        name="artifact_update",
        description="Create or update a mission artifact such as a document, plan, draft, or patch proposal.",
        risk="write",
        input_schema=_schema(
            ["title", "body"],
            {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "kind": {"type": "string", "default": "markdown"},
            },
        ),
    ),
    ToolSpec(
        name="ask_user",
        description="Create a concise user decision request when the model cannot proceed safely.",
        risk="read",
        input_schema=_schema(
            ["question"],
            {
                "question": {"type": "string"},
                "reason": {"type": "string"},
            },
        ),
    ),
]


LEARNING_TOOL_SPECS = [
    ToolSpec(
        name="memory_write_candidate",
        description="Propose a memory update with evidence. This never directly mutates stable memory.",
        risk="write",
        input_schema=_schema(
            ["claim"],
            {
                "claim": {"type": "string"},
                "dimension": {"type": "string"},
                "scope": {"type": "string", "default": "global"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "evidence": {
                    "type": "array",
                    "items": {"type": "object"},
                    "default": [],
                },
            },
        ),
    ),
    ToolSpec(
        name="skill_propose_candidate",
        description="Propose or patch a draft skill from repeated successful behavior or user feedback.",
        risk="write",
        input_schema=_schema(
            ["name", "description", "body"],
            {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "body": {"type": "string"},
            },
        ),
    ),
    ToolSpec(
        name="tool_propose_candidate",
        description="Propose a generated tool integration with a structured spec and provenance.",
        risk="write",
        input_schema=_schema(
            ["name", "spec"],
            {
                "name": {"type": "string"},
                "spec": {"type": "object"},
            },
        ),
    ),
    ToolSpec(
        name="eval_propose_case",
        description="Propose an evaluation case that can validate a memory, skill, or tool improvement.",
        risk="write",
        input_schema=_schema(
            ["name", "case"],
            {
                "name": {"type": "string"},
                "case": {"type": "object"},
            },
        ),
    ),
    ToolSpec(
        name="learning_discard",
        description="Record that no useful learning candidate should be produced from this evidence.",
        risk="write",
        input_schema=_schema(["reason"], {"reason": {"type": "string"}}),
    ),
]


class ToolRegistry:
    def __init__(self) -> None:
        self._specs = {spec.name: spec for spec in [*CORE_TOOL_SPECS, *LEARNING_TOOL_SPECS]}
        self._handlers: dict[str, ToolHandler] = {
            "memory_search": self._memory_search,
            "memory_read": self._memory_read,
            "working_note": self._working_note,
            "skills_list": self._skills_list,
            "skill_view": self._skill_view,
            "artifact_update": self._artifact_update,
            "ask_user": self._ask_user,
            "memory_write_candidate": self._memory_write_candidate,
            "skill_propose_candidate": self._skill_propose_candidate,
            "tool_propose_candidate": self._tool_propose_candidate,
            "eval_propose_case": self._eval_propose_case,
            "learning_discard": self._learning_discard,
        }

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def spec(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise ToolError(f"unknown tool: {name}") from exc

    def execute(self, call: ToolCallEnvelope, context: ToolContext) -> ToolResult:
        spec = self.spec(call.name)
        handler = self._handlers[call.name]
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            result=handler(call.arguments, context),
        )

    def _memory_search(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        query = _require_str(args, "query")
        limit = int(args.get("limit", 5))
        return {"matches": MemoryEngine(context.store).search(query, limit=limit)}

    def _memory_read(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        candidate_id = _require_str(args, "id")
        candidate = context.store.get_memory_candidate(candidate_id)
        if not candidate:
            raise NotFoundError(f"memory not found: {candidate_id}")
        return {"memory": candidate}

    def _working_note(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        content = _require_str(args, "content")
        note_id = context.store.add_working_note(context.mission_id, context.run_id, content)
        return {"note_id": note_id}

    def _skills_list(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return {"skills": context.store.list_skills()}

    def _skill_view(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        name = _require_str(args, "name")
        skill = context.store.get_skill(name)
        if not skill:
            raise NotFoundError(f"skill not found: {name}")
        return {"skill": skill}

    def _artifact_update(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        title = _require_str(args, "title")
        body = _require_str(args, "body")
        kind = str(args.get("kind") or "markdown")
        artifact_id = context.store.upsert_artifact(context.mission_id, context.run_id, title, body, kind)
        return {"artifact_id": artifact_id}

    def _ask_user(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return {
            "decision": {
                "question": _require_str(args, "question"),
                "reason": str(args.get("reason") or ""),
                "status": "open",
            }
        }

    def _memory_write_candidate(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        claim = _require_str(args, "claim")
        candidate_id = context.store.add_memory_candidate(
            context.run_id,
            claim,
            dimension=_optional_str(args, "dimension"),
            scope=str(args.get("scope") or "global"),
            confidence=float(args.get("confidence", 0.5)),
            evidence=args.get("evidence") or [],
        )
        return {"candidate_id": candidate_id, "status": "draft"}

    def _skill_propose_candidate(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        skill_id = context.store.upsert_skill(
            _require_str(args, "name"),
            _require_str(args, "description"),
            _require_str(args, "body"),
            source=f"run:{context.run_id}",
        )
        return {"skill_id": skill_id, "status": "draft"}

    def _tool_propose_candidate(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        candidate_id = context.store.add_tool_candidate(
            context.run_id,
            _require_str(args, "name"),
            _require_dict(args, "spec"),
        )
        return {"candidate_id": candidate_id, "status": "draft"}

    def _eval_propose_case(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        case_id = context.store.add_eval_case(
            context.run_id,
            _require_str(args, "name"),
            _require_dict(args, "case"),
        )
        return {"case_id": case_id, "status": "draft"}

    def _learning_discard(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        reason = _require_str(args, "reason")
        context.ledger.append(context.run_id, "learning.discarded", {"reason": reason})
        return {"discarded": True, "reason": reason}


class ToolHarness:
    def __init__(
        self,
        *,
        store: StateStore,
        ledger: RunLedger,
        registry: ToolRegistry | None = None,
        policy: ToolExecutionPolicy | None = None,
    ):
        self.store = store
        self.ledger = ledger
        self.registry = registry or ToolRegistry()
        self.policy = policy or ToolExecutionPolicy()

    def execute(self, call: ToolCallEnvelope, *, run_id: str, mission_id: str) -> ToolResult:
        spec = self.registry.spec(call.name)
        permission = self.policy.check(spec)
        started_at = time.time()
        self.ledger.append(
            run_id,
            "tool.called",
            {
                "call_id": call.call_id,
                "provider": call.provider,
                "tool_name": call.name,
                "risk": spec.risk,
                "arguments": call.arguments,
                "permission": asdict(permission),
            },
        )
        if not permission.allowed:
            return self._deny(call, spec, permission, run_id, started_at)

        context = ToolContext(store=self.store, ledger=self.ledger, run_id=run_id, mission_id=mission_id)
        try:
            result = _with_boundary_payload(self.registry.execute(call, context))
            ended_at = time.time()
            self.store.record_tool_call(
                run_id=run_id,
                provider=call.provider,
                provider_call_id=call.call_id,
                tool_name=call.name,
                args=call.arguments,
                risk=spec.risk,
                status="completed",
                result=result.result,
                started_at=started_at,
                ended_at=ended_at,
            )
            self.ledger.append(
                run_id,
                "tool.result",
                {
                    "call_id": call.call_id,
                    "tool_name": call.name,
                    "ok": True,
                    "result": result.result,
                    "summary": result.summary,
                    "evidence": result.evidence,
                },
            )
            return result
        except Exception as exc:
            ended_at = time.time()
            error = str(exc)
            result = _with_boundary_payload(ToolResult(call_id=call.call_id, name=call.name, ok=False, error=error))
            self.store.record_tool_call(
                run_id=run_id,
                provider=call.provider,
                provider_call_id=call.call_id,
                tool_name=call.name,
                args=call.arguments,
                risk=spec.risk,
                status="failed",
                error=error,
                started_at=started_at,
                ended_at=ended_at,
            )
            self.ledger.append(
                run_id,
                "tool.result",
                {
                    "call_id": call.call_id,
                    "tool_name": call.name,
                    "ok": False,
                    "error": error,
                    "summary": result.summary,
                    "evidence": result.evidence,
                },
            )
            return result

    def _deny(
        self,
        call: ToolCallEnvelope,
        spec: ToolSpec,
        permission: ToolPermission,
        run_id: str,
        started_at: float,
    ) -> ToolResult:
        ended_at = time.time()
        result = _with_boundary_payload(
            ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                error=permission.reason,
                result={"permission": asdict(permission)},
            )
        )
        self.store.record_tool_call(
            run_id=run_id,
            provider=call.provider,
            provider_call_id=call.call_id,
            tool_name=call.name,
            args=call.arguments,
            risk=spec.risk,
            status="denied",
            result=result.result,
            error=permission.reason,
            started_at=started_at,
            ended_at=ended_at,
        )
        self.ledger.append(
            run_id,
            "tool.denied",
            {
                "call_id": call.call_id,
                "tool_name": call.name,
                "risk": spec.risk,
                "reason": permission.reason,
            },
        )
        self.ledger.append(
            run_id,
            "tool.result",
            {
                "call_id": call.call_id,
                "tool_name": call.name,
                "ok": False,
                "error": permission.reason,
                "summary": result.summary,
                "evidence": result.evidence,
            },
        )
        return result


def tool_specs_as_json_schema(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "risk": spec.risk,
            "input_schema": spec.input_schema,
        }
        for spec in specs
    ]


def compact_tool_result(result: ToolResult) -> dict[str, Any]:
    """Compact payload sent back to the model after a tool call."""
    compact: dict[str, Any] = {
        "ok": result.ok,
        "tool": result.name,
        "summary": result.summary or _tool_summary(result),
    }
    if result.error:
        compact["error"] = result.error
    if result.evidence:
        compact["evidence"] = result.evidence
    return compact


def _with_boundary_payload(result: ToolResult) -> ToolResult:
    return replace(
        result,
        summary=result.summary or _tool_summary(result),
        evidence=result.evidence or _tool_evidence(result),
    )


def _tool_summary(result: ToolResult) -> str:
    if not result.ok:
        return result.error or "Tool call failed."
    if result.name == "memory_write_candidate":
        return "Memory candidate recorded for later consolidation."
    if result.name == "memory_search":
        return f"Found {len(result.result.get('matches', []))} memory matches."
    if result.name == "memory_read":
        return "Memory item loaded."
    if result.name == "working_note":
        return "Working note recorded."
    if result.name == "skills_list":
        return f"Listed {len(result.result.get('skills', []))} skills."
    if result.name == "skill_view":
        skill = result.result.get("skill") or {}
        return f"Loaded skill: {skill.get('name', 'unknown')}."
    if result.name == "artifact_update":
        return "Artifact updated."
    if result.name == "ask_user":
        return "User decision requested."
    if result.name in {"skill_propose_candidate", "tool_propose_candidate", "eval_propose_case"}:
        return "Learning candidate recorded."
    if result.name == "learning_discard":
        return "Learning evidence discarded."
    return "Tool call completed."


def _tool_evidence(result: ToolResult) -> list[dict[str, Any]]:
    if not result.ok:
        return [
            {
                "kind": "tool_error",
                "tool_name": result.name,
                "summary": result.error or "Tool call failed.",
            }
        ]
    if result.name == "memory_write_candidate":
        return [_evidence("memory_candidate", result.result.get("candidate_id"), "Memory candidate")]
    if result.name == "memory_search":
        matches = result.result.get("matches", [])
        return [
            {
                "kind": "memory_search",
                "summary": f"{len(matches)} matches",
                "items": [_compact_memory_match(item) for item in matches[:5]],
            }
        ]
    if result.name == "memory_read":
        memory = result.result.get("memory") or {}
        return [_evidence("memory", memory.get("id"), str(memory.get("claim") or memory.get("title") or "Memory"))]
    if result.name == "working_note":
        return [_evidence("working_note", result.result.get("note_id"), "Working note")]
    if result.name == "skills_list":
        return [
            {
                "kind": "skills_index",
                "summary": f"{len(result.result.get('skills', []))} skills",
                "items": [
                    {
                        "name": skill.get("name"),
                        "description": skill.get("description"),
                        "status": skill.get("status"),
                    }
                    for skill in result.result.get("skills", [])[:10]
                ],
            }
        ]
    if result.name == "skill_view":
        skill = result.result.get("skill") or {}
        return [_evidence("skill", skill.get("id") or skill.get("name"), str(skill.get("name") or "Skill"))]
    if result.name == "artifact_update":
        return [_evidence("artifact", result.result.get("artifact_id"), "Artifact")]
    if result.name == "ask_user":
        decision = result.result.get("decision") or {}
        return [_evidence("decision", result.call_id, str(decision.get("question") or "Decision request"))]
    return []


def _evidence(kind: str, item_id: Any, title: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": str(item_id or ""),
        "title": title,
    }


def _compact_memory_match(item: dict[str, Any]) -> dict[str, Any]:
    title = item.get("title") or item.get("claim") or ""
    return {
        "id": item.get("id"),
        "type": item.get("type"),
        "title": str(title)[:160],
        "confidence": item.get("confidence"),
    }


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"missing string argument: {key}")
    return value.strip()


def _optional_str(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"expected string argument: {key}")
    return value.strip() or None


def _require_dict(args: dict[str, Any], key: str) -> dict[str, Any]:
    value = args.get(key)
    if not isinstance(value, dict):
        raise ToolError(f"missing object argument: {key}")
    return value
