from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.errors import NotFoundError, ToolError
from ..core.jsonutil import dumps
from ..core.models import ToolCallEnvelope, ToolExecutionPolicy, ToolPermission, ToolResult, ToolSpec
from ..core.text_patch import optional_bool
from ..memory import MemoryEngine
from ..skills import SkillService
from ..storage import StateStore
from .evolution import ToolEvolutionService, validate_alias_implementation
from .standard import STANDARD_TOOL_SPECS, standard_tool_evidence, standard_tool_handlers, standard_tool_summary

if TYPE_CHECKING:
    from ..runtime.ledger import RunLedger


ToolHandler = Callable[[dict[str, Any], "ToolContext"], dict[str, Any]]
TOOL_SCHEMA_SERIALIZER_VERSION = "mnemo.tool_schema.v1"
DEFAULT_TOOL_PROFILE = "full.v1"
MINIMAL_TOOL_PROFILE = "minimal.v1"
CAPSULE_TOOL_PROFILE = "capsule.v1"
LEARNING_TOOL_PROFILE = "learning.v1"
DISCOVERY_TOOL_NAMES = ("tool_search", "tool_expand_schema")
LEARNING_REFLECTION_TOOL_NAMES = (
    "memory_write_candidate",
    "skill_propose_candidate",
    "tool_propose_candidate",
    "eval_propose_case",
    "learning_discard",
)


@dataclass(frozen=True)
class ToolBundle:
    bundle_id: str
    epoch: int
    profile: str
    provider_adapter_version: str
    schema_serializer_version: str
    tool_names: tuple[str, ...]
    schema_token_estimate: int
    specs: tuple[ToolSpec, ...]
    cache_bust_reason: str = "initial"

    def metadata(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "epoch": self.epoch,
            "profile": self.profile,
            "provider_adapter_version": self.provider_adapter_version,
            "schema_serializer_version": self.schema_serializer_version,
            "tool_count": len(self.tool_names),
            "tool_names": list(self.tool_names),
            "schema_token_estimate": self.schema_token_estimate,
            "cache_bust_reason": self.cache_bust_reason,
        }


class ToolContext:
    def __init__(self, *, store: StateStore, ledger: "RunLedger", run_id: str, mission_id: str, workspace_root: Path):
        self.store = store
        self.ledger = ledger
        self.run_id = run_id
        self.mission_id = mission_id
        self.workspace_root = workspace_root


def _schema(required: list[str], properties: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


CORE_TOOL_SPECS = [
    ToolSpec(
        name="tool_search",
        description="Search available tool cards without loading full provider schemas.",
        risk="read",
        input_schema=_schema(
            [],
            {
                "query": {"type": "string"},
                "risk": {"type": "string", "enum": ["read", "write", "external", "admin"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
        ),
    ),
    ToolSpec(
        name="tool_expand_schema",
        description="Request additional provider-native tool schemas for the next model round.",
        risk="read",
        input_schema=_schema(
            ["names"],
            {
                "names": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 50,
                    "items": {"type": "string"},
                }
            },
        ),
    ),
    ToolSpec(
        name="memory_search",
        description="Search stable memory, prior session snippets, or both by query.",
        risk="read",
        input_schema=_schema(
            ["query"],
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "search_scope": {
                    "type": "string",
                    "enum": ["memory", "stable", "sessions", "all"],
                    "default": "memory",
                },
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
        name="memory_health_report",
        description="Read compact memory health counts and model-actionable review cards.",
        risk="read",
        input_schema=_schema(
            [],
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
        ),
    ),
    ToolSpec(
        name="memory_tombstone",
        description="Move a memory candidate or stable page out of active use and record a durable tombstone.",
        risk="write",
        input_schema=_schema(
            ["id", "reason"],
            {
                "id": {"type": "string"},
                "reason": {"type": "string"},
                "target_type": {
                    "type": "string",
                    "enum": ["auto", "candidate", "page"],
                    "default": "auto",
                },
            },
        ),
    ),
    ToolSpec(
        name="recall_search",
        description="Find compact, actionable cards across memory, prior work, artifacts, and decisions.",
        risk="read",
        input_schema=_schema(
            ["query"],
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                "scope": {
                    "type": "string",
                    "enum": ["all", "knowledge", "past_work", "artifacts", "decisions"],
                    "default": "all",
                },
            },
        ),
    ),
    ToolSpec(
        name="working_note",
        description="Record a short mission-scoped working note. Set retention=memory_candidate only when this note should enter DreamCycle as a long-term memory candidate.",
        risk="write",
        input_schema=_schema(
            ["content"],
            {
                "content": {"type": "string"},
                "retention": {
                    "type": "string",
                    "enum": ["ephemeral", "memory_candidate"],
                    "default": "ephemeral",
                },
                "dimension": {"type": "string"},
                "scope": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        ),
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
        risk="write",
        input_schema=_schema(
            ["question"],
            {
                "question": {"type": "string"},
                "reason": {"type": "string"},
            },
        ),
    ),
    ToolSpec(
        name="watch_feedback",
        description="Record compact feedback for a Watch and apply an explicit model policy decision such as sparsify, pause, or disable.",
        risk="write",
        input_schema=_schema(
            ["item_id", "outcome"],
            {
                "item_id": {"type": "string"},
                "outcome": {
                    "type": "string",
                    "enum": ["notified", "silent", "no_feedback", "useful", "not_useful", "dismissed"],
                },
                "note": {"type": "string"},
                "decision": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["keep", "sparsify", "pause", "disable"]},
                        "schedule": {"type": "string"},
                        "reason": {"type": "string"},
                        "source": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
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
        name="skill_patch_candidate",
        description="Create a draft skill candidate by applying exact replacements to an existing skill body.",
        risk="write",
        input_schema=_schema(
            ["source_name", "name", "replacements"],
            {
                "source_name": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "replacements": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["old", "new"],
                        "properties": {
                            "old": {"type": "string"},
                            "new": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
                "replace_all": {"type": "boolean", "default": False},
            },
        ),
    ),
    ToolSpec(
        name="skill_review_candidate",
        description="Review a draft skill candidate and mark it ready or blocked before explicit promotion.",
        risk="write",
        input_schema=_schema(["name"], {"name": {"type": "string"}}),
    ),
    ToolSpec(
        name="skill_crystallize_from_run",
        description="Crystallize a completed successful run trace into a draft skill candidate for later review/eval/promotion.",
        risk="write",
        input_schema=_schema(
            ["run_id", "name"],
            {
                "run_id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "notes": {"type": "string"},
            },
        ),
    ),
    ToolSpec(
        name="skill_run_eval_case",
        description="Run a structured eval case against a skill and record the pass/fail result.",
        risk="write",
        input_schema=_schema(["case_id"], {"case_id": {"type": "string"}}),
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
        name="eval_record_result",
        description="Record the result of a proposed eval case for memory, skill, or tool evolution.",
        risk="write",
        input_schema=_schema(
            ["case_id", "status"],
            {
                "case_id": {"type": "string"},
                "status": {"type": "string", "enum": ["passed", "failed"]},
                "result": {"type": "object", "default": {}},
            },
        ),
    ),
    ToolSpec(
        name="tool_review_candidate",
        description="Review a generated tool candidate against spec validation and passed linked eval cases.",
        risk="write",
        input_schema=_schema(
            ["candidate_id"],
            {
                "candidate_id": {"type": "string"},
            },
        ),
    ),
    ToolSpec(
        name="tool_install_candidate",
        description="Install a ready generated tool candidate as an active alias to an existing tool.",
        risk="write",
        input_schema=_schema(
            ["candidate_id"],
            {
                "candidate_id": {"type": "string"},
            },
        ),
    ),
    ToolSpec(
        name="tool_uninstall_generated",
        description="Disable an installed generated tool by name without deleting its candidate history.",
        risk="write",
        input_schema=_schema(
            ["name"],
            {
                "name": {"type": "string"},
            },
        ),
    ),
    ToolSpec(
        name="tool_rollback_generated",
        description="Rollback an installed generated tool after a bad activation and require candidate review before reinstall.",
        risk="write",
        input_schema=_schema(
            ["name"],
            {
                "name": {"type": "string"},
                "reason": {"type": "string"},
            },
        ),
    ),
    ToolSpec(
        name="skill_record_outcome",
        description="Record the observed outcome of using a skill so future skill selection can improve.",
        risk="write",
        input_schema=_schema(
            ["name", "outcome"],
            {
                "name": {"type": "string"},
                "outcome": {"type": "string", "enum": ["success", "failure", "neutral"]},
                "score": {"type": "number", "minimum": -1, "maximum": 1},
                "evidence": {
                    "type": "array",
                    "items": {"type": "object"},
                    "default": [],
                },
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
    def __init__(self, *, generated_tools: Iterable[dict[str, Any]] | None = None) -> None:
        self._specs = {spec.name: spec for spec in [*CORE_TOOL_SPECS, *STANDARD_TOOL_SPECS, *LEARNING_TOOL_SPECS]}
        self._handlers: dict[str, ToolHandler] = {
            "tool_search": self._tool_search,
            "tool_expand_schema": self._tool_expand_schema,
            "memory_search": self._memory_search,
            "memory_read": self._memory_read,
            "memory_health_report": self._memory_health_report,
            "memory_tombstone": self._memory_tombstone,
            "recall_search": self._recall_search,
            "working_note": self._working_note,
            "skills_list": self._skills_list,
            "skill_view": self._skill_view,
            "artifact_update": self._artifact_update,
            "ask_user": self._ask_user,
            "watch_feedback": self._watch_feedback,
            **standard_tool_handlers(),
            "memory_write_candidate": self._memory_write_candidate,
            "skill_propose_candidate": self._skill_propose_candidate,
            "skill_patch_candidate": self._skill_patch_candidate,
            "skill_review_candidate": self._skill_review_candidate,
            "skill_crystallize_from_run": self._skill_crystallize_from_run,
            "skill_run_eval_case": self._skill_run_eval_case,
            "tool_propose_candidate": self._tool_propose_candidate,
            "eval_propose_case": self._eval_propose_case,
            "eval_record_result": self._eval_record_result,
            "tool_review_candidate": self._tool_review_candidate,
            "tool_install_candidate": self._tool_install_candidate,
            "tool_uninstall_generated": self._tool_uninstall_generated,
            "tool_rollback_generated": self._tool_rollback_generated,
            "skill_record_outcome": self._skill_record_outcome,
            "learning_discard": self._learning_discard,
        }
        self.load_generated_tools(generated_tools or [])

    @classmethod
    def from_store(cls, store: StateStore) -> "ToolRegistry":
        return cls(generated_tools=store.list_generated_tools(status="active", limit=100))

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def tool_bundle(
        self,
        *,
        profile: str = DEFAULT_TOOL_PROFILE,
        provider_adapter_version: str = "local",
        schema_serializer_version: str = TOOL_SCHEMA_SERIALIZER_VERSION,
        selected_tool_names: Iterable[str] | None = None,
        epoch: int = 1,
        cache_bust_reason: str = "initial",
    ) -> ToolBundle:
        specs = _select_tool_specs(self._specs, profile=profile, selected_tool_names=selected_tool_names)
        tool_names = tuple(spec.name for spec in specs)
        schema_payload = tool_specs_as_json_schema(list(specs))
        bundle_payload = {
            "profile": profile,
            "provider_adapter_version": provider_adapter_version,
            "schema_serializer_version": schema_serializer_version,
            "tool_names": list(tool_names),
            "schemas": schema_payload,
        }
        digest = hashlib.sha256(dumps(bundle_payload).encode("utf-8")).hexdigest()[:16]
        return ToolBundle(
            bundle_id=f"tb_{digest}",
            epoch=max(1, int(epoch)),
            profile=profile,
            provider_adapter_version=provider_adapter_version,
            schema_serializer_version=schema_serializer_version,
            tool_names=tool_names,
            schema_token_estimate=_estimate_schema_tokens(schema_payload),
            specs=tuple(specs),
            cache_bust_reason=cache_bust_reason,
        )

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def load_generated_tools(self, generated_tools: Iterable[dict[str, Any]]) -> None:
        for generated_tool in generated_tools:
            if generated_tool.get("status") != "active":
                continue
            implementation = generated_tool.get("implementation") or {}
            if implementation.get("type") != "alias":
                continue
            name = generated_tool.get("name")
            if not isinstance(name, str) or name in self._specs:
                continue
            target_tool = implementation.get("target_tool")
            if not isinstance(target_tool, str) or target_tool not in self._handlers:
                continue
            candidate = {
                "name": generated_tool.get("name"),
                "spec": {
                    "name": generated_tool.get("name"),
                    "description": generated_tool.get("description"),
                    "risk": generated_tool.get("risk"),
                    "input_schema": generated_tool.get("input_schema"),
                    "implementation": implementation,
                },
            }
            if validate_alias_implementation(candidate, self._specs):
                continue
            self.register(
                ToolSpec(
                    name=name,
                    description=str(generated_tool["description"]),
                    risk=generated_tool["risk"],
                    input_schema=generated_tool["input_schema"],
                ),
                self._generated_alias_handler(generated_tool),
            )

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

    def _tool_search(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        query = str(args.get("query") or "").strip().casefold()
        risk = _optional_str(args, "risk")
        limit = _bounded_limit(args.get("limit"), default=20, maximum=50)
        tools: list[dict[str, Any]] = []
        for spec in sorted(self._specs.values(), key=lambda item: item.name):
            if risk and spec.risk != risk:
                continue
            searchable = f"{spec.name} {spec.description}".casefold()
            if query and query not in searchable:
                continue
            tools.append({"name": spec.name, "description": spec.description, "risk": spec.risk})
            if len(tools) >= limit:
                break
        return {"tools": tools, "count": len(tools)}

    def _tool_expand_schema(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        requested = _require_str_list(args, "names")
        expanded: list[str] = []
        missing: list[str] = []
        for name in requested:
            if name in self._specs:
                expanded.append(name)
            else:
                missing.append(name)
        return {
            "expanded_tool_names": expanded,
            "missing_tool_names": missing,
            "status": "ready_next_round" if expanded else "no_matching_tools",
        }

    def _memory_search(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        query = _require_str(args, "query")
        limit = int(args.get("limit", 5))
        search_scope = _memory_search_scope(args)
        return MemoryEngine(context.store).search_with_plan(query, limit=limit, search_scope=search_scope)

    def _memory_read(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        memory_id = _require_str(args, "id")
        candidate = context.store.get_memory_candidate(memory_id)
        if candidate:
            return {
                "memory": {
                    "type": "candidate",
                    **candidate,
                    "tombstones": context.store.list_memory_tombstones(target_id=memory_id, limit=10),
                }
            }
        page = context.store.get_memory_page(memory_id)
        if page:
            return {
                "memory": {
                    "type": "page",
                    **page,
                    "tombstones": context.store.list_memory_tombstones(target_id=memory_id, limit=10),
                }
            }
        raise NotFoundError(f"memory not found: {memory_id}")

    def _memory_health_report(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        limit = _bounded_limit(args.get("limit"), default=20, maximum=50)
        return MemoryEngine(context.store).health_report(limit=limit)

    def _memory_tombstone(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        memory_id = _require_str(args, "id")
        reason = _require_str(args, "reason")
        target_type = _memory_tombstone_target_type(args)
        return MemoryEngine(context.store).tombstone_memory(memory_id, reason, target_type=target_type)

    def _recall_search(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        query = _require_str(args, "query")
        limit = _bounded_limit(args.get("limit"), default=8, maximum=20)
        scope = _recall_scope(args)
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        if scope in {"all", "knowledge"}:
            for match in MemoryEngine(context.store).search(query, limit=limit, search_scope="memory"):
                _append_recall_item(items, seen, _recall_knowledge_item(match))
        if scope in {"all", "past_work"}:
            for message in context.store.search_session_messages(query, limit=limit):
                if message.get("run_id") == context.run_id:
                    continue
                _append_recall_item(items, seen, _recall_session_item(message))
            for run in context.store.list_runs(limit=50):
                if run.get("id") == context.run_id:
                    continue
                if _query_matches(query, run.get("input_preview"), run.get("status")):
                    _append_recall_item(items, seen, _recall_run_item(run))
        if scope in {"all", "artifacts"}:
            for artifact in context.store.list_artifacts(limit=50):
                full_artifact = context.store.get_artifact(artifact["id"]) or artifact
                if _query_matches(query, full_artifact.get("title"), full_artifact.get("kind"), full_artifact.get("body")):
                    _append_recall_item(items, seen, _recall_artifact_item(full_artifact))
        if scope in {"all", "decisions"}:
            for item in context.store.list_inbox_items(status=None, limit=50):
                if _query_matches(
                    query,
                    item.get("title"),
                    item.get("body"),
                    item.get("category"),
                    item.get("status"),
                    item.get("resolution"),
                ):
                    _append_recall_item(items, seen, _recall_decision_item(item))

        return {
            "query": query,
            "scope": scope,
            "count": len(items[:limit]),
            "items": items[:limit],
        }

    def _working_note(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        content = _require_str(args, "content")
        metadata = {
            "retention": _working_note_retention(args),
            "dimension": _optional_str(args, "dimension"),
            "scope": _optional_str(args, "scope"),
            "confidence": _optional_float(args, "confidence"),
        }
        note_id = context.store.add_working_note(context.mission_id, context.run_id, content, metadata=metadata)
        return {"note_id": note_id, "retention": metadata["retention"]}

    def _skills_list(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return {"skills": SkillService(context.store).context_cards(limit=50)}

    def _skill_view(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        name = _require_str(args, "name")
        skill = context.store.get_skill(name)
        if not skill:
            raise NotFoundError(f"skill not found: {name}")
        context.store.record_skill_usage(
            context.run_id,
            name,
            "viewed",
            evidence=[{"kind": "tool_call", "call": "skill_view"}],
        )
        return {"skill": skill}

    def _artifact_update(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        title = _require_str(args, "title")
        body = _require_str(args, "body")
        kind = str(args.get("kind") or "markdown")
        artifact_id = context.store.upsert_artifact(context.mission_id, context.run_id, title, body, kind)
        return {"artifact_id": artifact_id, "title": title, "kind": kind}

    def _ask_user(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        question = _require_str(args, "question")
        reason = str(args.get("reason") or "")
        item_id = context.store.add_inbox_item(
            category="decision",
            title=question,
            priority=1,
            body=reason or None,
            action_type="choose",
            action_data={
                "options": [
                    {"id": "accepted", "label": "Approve"},
                    {"id": "rejected", "label": "Reject"},
                    {"id": "ignored", "label": "Ignore"},
                ],
                "source": "ask_user",
            },
            source_run_id=context.run_id,
        )
        return {
            "decision": {
                "item_id": item_id,
                "question": question,
                "reason": reason,
                "status": "open",
                "options": ["accepted", "rejected", "ignored"],
            }
        }

    def _watch_feedback(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        decision = args.get("decision")
        if decision is not None and not isinstance(decision, dict):
            raise ToolError("decision must be an object")
        from ..runtime.scheduler import ScheduleService

        return ScheduleService(context.store.state_dir).record_watch_feedback(
            _require_str(args, "item_id"),
            outcome=_require_str(args, "outcome"),
            note=str(args.get("note") or ""),
            decision=decision,
        )

    def _memory_write_candidate(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        claim = _require_str(args, "claim")
        confidence = _optional_float(args, "confidence") if "confidence" in args else None
        return MemoryEngine(context.store).write_candidate(
            context.run_id,
            claim,
            dimension=_optional_str(args, "dimension"),
            scope=str(args.get("scope") or "global"),
            confidence=0.5 if confidence is None else confidence,
            evidence=_optional_evidence(args.get("evidence")),
        )

    def _skill_propose_candidate(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        skill_id = context.store.upsert_skill(
            _require_str(args, "name"),
            _require_str(args, "description"),
            _require_str(args, "body"),
            source=f"run:{context.run_id}",
        )
        return {"skill_id": skill_id, "status": "draft"}

    def _skill_patch_candidate(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return SkillService(context.store).patch_candidate(
            _require_str(args, "source_name"),
            _require_str(args, "name"),
            args.get("replacements"),
            description=_optional_str(args, "description"),
            replace_all=optional_bool(args.get("replace_all"), default=False),
        )

    def _skill_review_candidate(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return SkillService(context.store).review(_require_str(args, "name"))

    def _skill_crystallize_from_run(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return SkillService(context.store).crystallize_from_run(
            _require_str(args, "run_id"),
            _require_str(args, "name"),
            description=_optional_str(args, "description"),
            notes=_optional_str(args, "notes"),
        )

    def _skill_run_eval_case(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return SkillService(context.store).run_eval_case(_require_str(args, "case_id"))

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

    def _eval_record_result(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        case_id = _require_str(args, "case_id")
        status = _require_eval_status(args, "status")
        if not context.store.get_eval_case(case_id):
            raise NotFoundError(f"eval case not found: {case_id}")
        context.store.update_eval_case_status(
            case_id,
            status,
            result=args.get("result") if isinstance(args.get("result"), dict) else {},
        )
        return {"case_id": case_id, "status": status}

    def _tool_review_candidate(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return ToolEvolutionService(context.store).review_candidate(_require_str(args, "candidate_id"))

    def _tool_install_candidate(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        result = ToolEvolutionService(context.store).install_candidate(
            _require_str(args, "candidate_id"),
            available_tools=self._specs,
        )
        if result.get("installed"):
            installed = context.store.get_generated_tool(str(result["name"]))
            if installed:
                self.load_generated_tools([installed])
        return result

    def _tool_uninstall_generated(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        result = ToolEvolutionService(context.store).uninstall_generated_tool(_require_str(args, "name"))
        name = str(result["name"])
        if name in self._specs:
            self._specs.pop(name)
            self._handlers.pop(name, None)
        return result

    def _tool_rollback_generated(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        result = ToolEvolutionService(context.store).rollback_generated_tool(
            _require_str(args, "name"),
            reason=str(args.get("reason") or ""),
        )
        name = str(result["name"])
        if name in self._specs:
            self._specs.pop(name)
            self._handlers.pop(name, None)
        return result

    def _skill_record_outcome(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        name = _require_str(args, "name")
        outcome = _require_outcome(args, "outcome")
        event_id = context.store.record_skill_usage(
            context.run_id,
            name,
            "outcome",
            outcome=outcome,
            score=_outcome_score(args, outcome),
            evidence=args.get("evidence") or [],
        )
        return {"event_id": event_id, "name": name, "outcome": outcome}

    def _learning_discard(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        reason = _require_str(args, "reason")
        context.ledger.append(context.run_id, "learning.discarded", {"reason": reason})
        return {"discarded": True, "reason": reason}

    def _generated_alias_handler(self, generated_tool: dict[str, Any]) -> ToolHandler:
        name = str(generated_tool["name"])
        implementation = generated_tool["implementation"]
        target_tool = str(implementation["target_tool"])
        argument_map = implementation.get("argument_map") or {}

        def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
            target_args = _map_alias_arguments(args, argument_map)
            target_result = self._handlers[target_tool](target_args, context)
            return {
                "generated_tool": name,
                "target_tool": target_tool,
                "target_result": target_result,
            }

        return handler


class ToolHarness:
    def __init__(
        self,
        *,
        store: StateStore,
        ledger: "RunLedger",
        registry: ToolRegistry | None = None,
        policy: ToolExecutionPolicy | None = None,
        workspace_root: str | Path | None = None,
    ):
        self.store = store
        self.ledger = ledger
        self.registry = registry or ToolRegistry.from_store(store)
        self.policy = policy or ToolExecutionPolicy()
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()

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

        context = ToolContext(
            store=self.store,
            ledger=self.ledger,
            run_id=run_id,
            mission_id=mission_id,
            workspace_root=self.workspace_root,
        )
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
        result_payload: dict[str, Any] = {"permission": asdict(permission)}
        decision = _approval_decision_for_denied_tool(self.store, call, spec, permission, run_id)
        if decision:
            result_payload["decision"] = decision
        result = _with_boundary_payload(
            ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                error=permission.reason,
                result=result_payload,
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
                "decision": decision,
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


def _select_tool_specs(
    specs_by_name: dict[str, ToolSpec],
    *,
    profile: str,
    selected_tool_names: Iterable[str] | None,
) -> tuple[ToolSpec, ...]:
    if selected_tool_names is None:
        selected_names = _profile_tool_names(specs_by_name, profile)
    else:
        selected_names = tuple(dict.fromkeys(str(name) for name in selected_tool_names if str(name) in specs_by_name))
        selected_names = _with_discovery_tools(selected_names, specs_by_name)
    return tuple(specs_by_name[name] for name in sorted(selected_names) if name in specs_by_name)


def _profile_tool_names(specs_by_name: dict[str, ToolSpec], profile: str) -> tuple[str, ...]:
    if profile == DEFAULT_TOOL_PROFILE:
        return tuple(specs_by_name)
    if profile == LEARNING_TOOL_PROFILE:
        return tuple(name for name in LEARNING_REFLECTION_TOOL_NAMES if name in specs_by_name)
    if profile in {MINIMAL_TOOL_PROFILE, CAPSULE_TOOL_PROFILE}:
        names = [
            name
            for name, spec in specs_by_name.items()
            if spec.risk == "read" and _is_profile_safe_tool(name)
        ]
        return _with_discovery_tools(names, specs_by_name)
    raise ToolError(f"unknown tool profile: {profile}")


def _is_profile_safe_tool(name: str) -> bool:
    if name in DISCOVERY_TOOL_NAMES:
        return True
    if name.startswith("tool_"):
        return True
    return name in {
        "memory_search",
        "memory_read",
        "memory_health_report",
        "recall_search",
        "skills_list",
        "skill_view",
        "file_search",
        "file_read",
        "web_fetch",
    }


def _with_discovery_tools(names: Iterable[str], specs_by_name: dict[str, ToolSpec]) -> tuple[str, ...]:
    ordered = list(dict.fromkeys(str(name) for name in names))
    for name in DISCOVERY_TOOL_NAMES:
        if name in specs_by_name and name not in ordered:
            ordered.append(name)
    return tuple(ordered)


def _estimate_schema_tokens(schema_payload: list[dict[str, Any]]) -> int:
    content = dumps(schema_payload)
    if not content:
        return 0
    return max(1, (len(content) + 3) // 4)


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
        decision = result.result.get("decision")
        if isinstance(decision, dict) and decision.get("item_id"):
            return f"Tool requires user approval: {decision.get('item_id')} ({result.error or 'not allowed'})."
        return result.error or "Tool call failed."
    if result.name == "memory_write_candidate":
        status = str(result.result.get("status") or "draft")
        if status.startswith("needs_review"):
            return f"Memory candidate recorded for review: {status}."
        return "Memory candidate recorded for later consolidation."
    if result.name == "memory_search":
        return f"Found {len(result.result.get('matches', []))} memory matches."
    if result.name == "recall_search":
        return f"Found {len(result.result.get('items', []))} recall items."
    if result.name == "tool_search":
        return f"Found {len(result.result.get('tools', []))} tool cards."
    if result.name == "tool_expand_schema":
        return f"Prepared {len(result.result.get('expanded_tool_names', []))} tool schemas for the next model round."
    if result.name == "memory_read":
        return "Memory item loaded."
    if result.name == "memory_health_report":
        return f"Memory health report has {len(result.result.get('review_cards', []))} review cards."
    if result.name == "memory_tombstone":
        return "Memory tombstone recorded."
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
    if result.name == "watch_feedback":
        item = result.result.get("item") or {}
        feedback = result.result.get("feedback") or {}
        decision = result.result.get("decision") or {}
        return (
            f"Watch feedback recorded: {feedback.get('last_outcome', 'unknown')} "
            f"action={decision.get('action', 'keep')} status={item.get('status', 'unknown')}."
        )
    standard_summary = standard_tool_summary(result)
    if standard_summary:
        return standard_summary
    if result.name == "skill_record_outcome":
        return f"Recorded skill outcome: {result.result.get('name', 'unknown')} {result.result.get('outcome', '')}."
    if result.name == "eval_record_result":
        return f"Recorded eval result: {result.result.get('status', 'unknown')}."
    if result.name == "tool_review_candidate":
        return f"Reviewed tool candidate: {result.result.get('status', 'unknown')}."
    if result.name == "tool_install_candidate":
        return f"Installed tool candidate: {result.result.get('status', 'unknown')}."
    if result.name == "tool_uninstall_generated":
        return f"Uninstalled generated tool: {result.result.get('name', 'unknown')}."
    if result.name == "tool_rollback_generated":
        return f"Rolled back generated tool: {result.result.get('name', 'unknown')}."
    if result.result.get("generated_tool") == result.name:
        return f"Ran generated tool {result.name} via {result.result.get('target_tool', 'unknown')}."
    if result.name == "skill_review_candidate":
        return f"Reviewed skill candidate: {result.result.get('status', 'unknown')}."
    if result.name == "skill_patch_candidate":
        return f"Patched draft skill candidate: {result.result.get('name', 'unknown')}."
    if result.name == "skill_crystallize_from_run":
        return f"Crystallized draft skill: {result.result.get('name', 'unknown')}."
    if result.name == "skill_run_eval_case":
        return f"Ran skill eval case: {result.result.get('status', 'unknown')}."
    if result.name in {"skill_propose_candidate", "tool_propose_candidate", "eval_propose_case"}:
        return "Learning candidate recorded."
    if result.name == "learning_discard":
        return "Learning evidence discarded."
    return "Tool call completed."


def _tool_evidence(result: ToolResult) -> list[dict[str, Any]]:
    if not result.ok:
        decision = result.result.get("decision")
        if isinstance(decision, dict) and decision.get("item_id"):
            return [
                {
                    "kind": "decision",
                    "id": str(decision.get("item_id") or ""),
                    "title": str(decision.get("question") or "Tool approval required"),
                    "status": decision.get("status") or "open",
                    "tool_name": result.name,
                    "risk": decision.get("risk"),
                }
            ]
        return [
            {
                "kind": "tool_error",
                "tool_name": result.name,
                "summary": result.error or "Tool call failed.",
            }
        ]
    if result.name == "memory_write_candidate":
        evidence = _evidence("memory_candidate", result.result.get("candidate_id"), "Memory candidate")
        evidence["status"] = result.result.get("status")
        if result.result.get("safety"):
            evidence["safety"] = result.result["safety"]
        return [evidence]
    if result.name == "skill_propose_candidate":
        evidence = _evidence("skill_candidate", result.result.get("skill_id"), "Skill candidate")
        evidence["status"] = result.result.get("status")
        return [evidence]
    if result.name == "tool_propose_candidate":
        evidence = _evidence("tool_candidate", result.result.get("candidate_id"), "Tool candidate")
        evidence["status"] = result.result.get("status")
        return [evidence]
    if result.name == "eval_propose_case":
        evidence = _evidence("eval_case", result.result.get("case_id"), "Eval case")
        evidence["status"] = result.result.get("status")
        return [evidence]
    if result.name == "memory_search":
        matches = result.result.get("matches", [])
        return [
            {
                "kind": "memory_search",
                "summary": f"{len(matches)} matches",
                "items": [_compact_memory_match(item) for item in matches[:5]],
            }
        ]
    if result.name == "recall_search":
        items = result.result.get("items", [])
        return [
            {
                "kind": "recall_search",
                "summary": f"{len(items)} items",
                "items": [_compact_recall_item(item) for item in items[:6]],
            }
        ]
    if result.name == "tool_search":
        tools = result.result.get("tools", [])
        return [
            {
                "kind": "tool_search",
                "summary": f"{len(tools)} tool cards",
                "items": tools[:10],
            }
        ]
    if result.name == "tool_expand_schema":
        return [
            {
                "kind": "tool_bundle_expansion",
                "expanded_tool_names": result.result.get("expanded_tool_names", []),
                "missing_tool_names": result.result.get("missing_tool_names", []),
            }
        ]
    if result.name == "memory_read":
        memory = result.result.get("memory") or {}
        return [_evidence("memory", memory.get("id"), str(memory.get("claim") or memory.get("title") or "Memory"))]
    if result.name == "watch_feedback":
        item = result.result.get("item") or {}
        feedback = result.result.get("feedback") or {}
        decision = result.result.get("decision") or {}
        return [
            {
                "kind": "watch_feedback",
                "id": item.get("id"),
                "title": item.get("title"),
                "outcome": feedback.get("last_outcome"),
                "decision_action": decision.get("action"),
                "status": item.get("status"),
                "schedule": item.get("schedule"),
            }
        ]
    if result.name == "memory_health_report":
        counts = result.result.get("counts") or {}
        score = result.result.get("score") or {}
        return [
            {
                "kind": "memory_health",
                "summary": f"{len(result.result.get('review_cards', []))} review cards",
                "counts": counts,
                "score": score,
                "review_cards": result.result.get("review_cards", [])[:5],
            }
        ]
    if result.name == "memory_tombstone":
        return [
            {
                "kind": "memory_tombstone",
                "id": str(result.result.get("tombstone_id") or ""),
                "target_id": result.result.get("memory_id"),
                "target_type": result.result.get("target_type"),
                "reason": result.result.get("reason"),
            }
        ]
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
    if result.name == "skill_record_outcome":
        return [
            {
                "kind": "skill_outcome",
                "id": str(result.result.get("event_id") or ""),
                "title": str(result.result.get("name") or "Skill"),
                "outcome": result.result.get("outcome"),
            }
        ]
    if result.name == "eval_record_result":
        return [_evidence("eval_case", result.result.get("case_id"), str(result.result.get("status") or "Eval result"))]
    if result.name == "tool_review_candidate":
        return [
            {
                "kind": "tool_candidate_review",
                "id": str(result.result.get("candidate_id") or ""),
                "title": str(result.result.get("name") or "Tool candidate"),
                "status": result.result.get("status"),
                "errors": result.result.get("errors", [])[:5],
                "passed_eval_case_ids": result.result.get("passed_eval_case_ids", [])[:10],
            }
        ]
    if result.name == "tool_install_candidate":
        return [
            {
                "kind": "generated_tool_install",
                "id": str(result.result.get("tool_id") or result.result.get("candidate_id") or ""),
                "title": str(result.result.get("name") or "Generated tool"),
                "status": result.result.get("status"),
                "target_tool": result.result.get("target_tool"),
                "errors": result.result.get("errors", [])[:5],
            }
        ]
    if result.name == "tool_uninstall_generated":
        return [
            {
                "kind": "generated_tool_uninstall",
                "id": str(result.result.get("name") or ""),
                "title": str(result.result.get("name") or "Generated tool"),
                "status": result.result.get("status"),
            }
        ]
    if result.name == "tool_rollback_generated":
        return [
            {
                "kind": "generated_tool_rollback",
                "id": str(result.result.get("name") or ""),
                "title": str(result.result.get("name") or "Generated tool"),
                "status": result.result.get("status"),
                "previous_status": result.result.get("previous_status"),
                "candidate_status": result.result.get("candidate_status"),
                "reason": result.result.get("reason", ""),
            }
        ]
    if result.result.get("generated_tool") == result.name:
        return [
            {
                "kind": "generated_tool",
                "id": result.name,
                "title": result.name,
                "target_tool": result.result.get("target_tool"),
            }
        ]
    if result.name == "skill_review_candidate":
        return [
            {
                "kind": "skill_candidate_review",
                "id": str(result.result.get("name") or ""),
                "title": str(result.result.get("name") or "Skill candidate"),
                "status": result.result.get("status"),
                "errors": result.result.get("errors", [])[:5],
            }
        ]
    if result.name == "skill_patch_candidate":
        return [
            {
                "kind": "skill_patch_candidate",
                "id": str(result.result.get("skill_id") or ""),
                "title": str(result.result.get("name") or "Skill patch candidate"),
                "source_skill": result.result.get("source_skill"),
                "replacement_count": sum(item.get("count", 0) for item in result.result.get("replacements", [])),
            }
        ]
    if result.name == "skill_crystallize_from_run":
        return [
            {
                "kind": "skill_crystallization",
                "id": str(result.result.get("skill_id") or ""),
                "title": str(result.result.get("name") or "Skill candidate"),
                "status": result.result.get("status"),
                "source_run_id": result.result.get("source_run_id"),
                "tools": result.result.get("tool_names", [])[:10],
            }
        ]
    if result.name == "skill_run_eval_case":
        return [
            {
                "kind": "skill_eval_case",
                "id": str(result.result.get("case_id") or ""),
                "title": str(result.result.get("skill_name") or "Skill eval"),
                "status": result.result.get("status"),
                "errors": result.result.get("errors", [])[:5],
            }
        ]
    if result.name == "artifact_update":
        return [_evidence("artifact", result.result.get("artifact_id"), "Artifact")]
    if result.name == "ask_user":
        decision = result.result.get("decision") or {}
        return [_evidence("decision", decision.get("item_id") or result.call_id, str(decision.get("question") or "Decision request"))]
    standard_evidence = standard_tool_evidence(result)
    if standard_evidence is not None:
        return standard_evidence
    return []


def _evidence(kind: str, item_id: Any, title: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": str(item_id or ""),
        "title": title,
    }


def _approval_decision_for_denied_tool(
    store: StateStore,
    call: ToolCallEnvelope,
    spec: ToolSpec,
    permission: ToolPermission,
    run_id: str,
) -> dict[str, Any] | None:
    if spec.risk not in {"external", "admin"}:
        return None
    question = f"Approve {spec.name}?"
    item_id = store.add_inbox_item(
        category="decision",
        title=question,
        priority=0 if spec.risk == "admin" else 1,
        body=permission.reason,
        action_type="tool_approval",
        action_data={
            "options": [
                {"id": "accepted", "label": "Approve"},
                {"id": "rejected", "label": "Reject"},
                {"id": "ignored", "label": "Ignore"},
            ],
            "source": "tool_policy",
            "tool_call": {
                "call_id": call.call_id,
                "provider": call.provider,
                "tool_name": spec.name,
                "risk": spec.risk,
                "arguments": _compact_tool_arguments(call.arguments),
            },
        },
        source_run_id=run_id,
    )
    return {
        "item_id": item_id,
        "question": question,
        "reason": permission.reason,
        "status": "open",
        "options": ["accepted", "rejected", "ignored"],
        "action_type": "tool_approval",
        "tool_name": spec.name,
        "risk": spec.risk,
    }


def _compact_tool_arguments(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            compact[str(key)] = _compact_tool_arguments(item, limit=max(120, limit // 2))
            if len(dumps(compact)) > limit:
                compact["..."] = "truncated"
                break
        return compact
    if isinstance(value, list):
        compact_items = [_compact_tool_arguments(item, limit=max(120, limit // 2)) for item in value[:10]]
        if len(value) > 10:
            compact_items.append("...[truncated]...")
        return compact_items
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 20)].rstrip() + "...[truncated]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:limit]


def _compact_memory_match(item: dict[str, Any]) -> dict[str, Any]:
    title = item.get("title") or item.get("claim") or ""
    if item.get("type") == "session_message":
        title = item.get("snippet") or title
    return {
        "id": item.get("id"),
        "type": item.get("type"),
        "title": str(title)[:160],
        "confidence": item.get("confidence"),
    }


def _compact_recall_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": item.get("kind"),
        "item_id": item.get("item_id"),
        "title": str(item.get("title") or "")[:160],
        "summary": str(item.get("summary") or "")[:220],
    }


def _append_recall_item(items: list[dict[str, Any]], seen: set[tuple[str, str]], item: dict[str, Any]) -> None:
    key = (str(item.get("kind") or ""), str(item.get("item_id") or ""))
    if not key[0] or not key[1] or key in seen:
        return
    seen.add(key)
    items.append(item)


def _recall_knowledge_item(match: dict[str, Any]) -> dict[str, Any]:
    source_type = str(match.get("type") or "memory")
    item_id = str(match.get("id") or "")
    title = match.get("title") or match.get("claim") or "Knowledge"
    summary = match.get("content") or match.get("claim") or match.get("snippet") or ""
    return {
        "kind": "knowledge",
        "item_id": item_id,
        "source_type": source_type,
        "title": _preview(str(title), limit=96),
        "summary": _preview(str(summary), limit=220),
        "confidence": match.get("confidence"),
        "status": match.get("status"),
        "actions": ["use"],
    }


def _recall_session_item(message: dict[str, Any]) -> dict[str, Any]:
    summary = str(message.get("snippet") or "")
    return {
        "kind": "past_work",
        "item_id": str(message.get("message_id") or message.get("id") or ""),
        "source_type": "session_message",
        "title": f"{message.get('role', 'message')} message",
        "summary": _preview(summary, limit=220),
        "conversation_id": message.get("conversation_id"),
        "mission_id": message.get("mission_id"),
        "run_id": message.get("run_id"),
        "actions": ["continue"],
    }


def _recall_run_item(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "past_work",
        "item_id": str(run.get("id") or ""),
        "source_type": "run",
        "title": "Past run",
        "summary": _preview(str(run.get("input_preview") or ""), limit=220),
        "conversation_id": run.get("conversation_id"),
        "mission_id": run.get("mission_id"),
        "run_id": run.get("id"),
        "status": run.get("status"),
        "actions": ["continue"],
    }


def _recall_artifact_item(artifact: dict[str, Any]) -> dict[str, Any]:
    title = str(artifact.get("title") or "Artifact")
    body = str(artifact.get("body") or "")
    return {
        "kind": "artifact",
        "item_id": str(artifact.get("id") or ""),
        "artifact_id": artifact.get("id"),
        "source_type": str(artifact.get("kind") or "artifact"),
        "title": _preview(title, limit=96),
        "summary": _preview(body or title, limit=220),
        "run_id": artifact.get("run_id"),
        "mission_id": artifact.get("mission_id"),
        "actions": ["open", "reuse"],
    }


def _recall_decision_item(item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or "Decision")
    body = str(item.get("body") or "")
    return {
        "kind": "decision",
        "item_id": str(item.get("id") or ""),
        "source_type": str(item.get("category") or "decision"),
        "title": _preview(title, limit=96),
        "summary": _preview(body or title, limit=220),
        "status": item.get("status"),
        "resolution": item.get("resolution"),
        "run_id": item.get("source_run_id"),
        "actions": ["resolve"] if item.get("status") == "open" else ["reuse"],
    }


def _query_matches(query: str, *values: Any) -> bool:
    terms = [term for term in query.casefold().split() if term]
    if not terms:
        return False
    haystack = " ".join(str(value or "") for value in values).casefold()
    return all(term in haystack for term in terms)


def _preview(value: str, limit: int = 220) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: max(0, limit - 1)].rstrip()}..."


def _bounded_limit(value: Any, *, default: int, maximum: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(maximum, limit))


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"missing string argument: {key}")
    return value.strip()


def _require_str_list(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if not isinstance(value, list) or not value:
        raise ToolError(f"missing string list argument: {key}")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ToolError(f"invalid string list argument: {key}")
        result.append(item.strip())
    return result


def _require_outcome(args: dict[str, Any], key: str) -> str:
    value = _require_str(args, key)
    if value not in {"success", "failure", "neutral"}:
        raise ToolError(f"invalid outcome: {value}")
    return value


def _require_eval_status(args: dict[str, Any], key: str) -> str:
    value = _require_str(args, key)
    if value not in {"passed", "failed"}:
        raise ToolError(f"invalid eval status: {value}")
    return value


def _outcome_score(args: dict[str, Any], outcome: str) -> float:
    if "score" not in args:
        return {"success": 1.0, "failure": -1.0, "neutral": 0.0}[outcome]
    try:
        score = float(args["score"])
    except (TypeError, ValueError) as exc:
        raise ToolError("score must be a number") from exc
    if score < -1 or score > 1:
        raise ToolError("score must be between -1 and 1")
    return score


def _working_note_retention(args: dict[str, Any]) -> str:
    retention = str(args.get("retention") or "ephemeral")
    if retention not in {"ephemeral", "memory_candidate"}:
        raise ToolError(f"invalid working note retention: {retention}")
    return retention


def _memory_search_scope(args: dict[str, Any]) -> str:
    scope = str(args.get("search_scope") or args.get("scope") or "memory")
    if scope not in {"memory", "stable", "sessions", "all"}:
        raise ToolError(f"invalid memory search scope: {scope}")
    return scope


def _memory_tombstone_target_type(args: dict[str, Any]) -> str:
    target_type = str(args.get("target_type") or "auto")
    if target_type not in {"auto", "candidate", "page"}:
        raise ToolError(f"invalid memory tombstone target_type: {target_type}")
    return target_type


def _recall_scope(args: dict[str, Any]) -> str:
    scope = str(args.get("scope") or "all")
    if scope not in {"all", "knowledge", "past_work", "artifacts", "decisions"}:
        raise ToolError(f"invalid recall scope: {scope}")
    return scope


def _optional_float(args: dict[str, Any], key: str) -> float | None:
    if key not in args or args.get(key) is None:
        return None
    try:
        value = float(args[key])
    except (TypeError, ValueError) as exc:
        raise ToolError(f"expected numeric argument: {key}") from exc
    if key == "confidence" and (value < 0 or value > 1):
        raise ToolError("confidence must be between 0 and 1")
    return value


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


def _optional_evidence(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolError("evidence must be a list")
    evidence: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ToolError("evidence items must be objects")
        evidence.append(item)
    return evidence


def _map_alias_arguments(args: dict[str, Any], argument_map: dict[str, Any]) -> dict[str, Any]:
    if not argument_map:
        return dict(args)
    mapped: dict[str, Any] = {}
    for target_key, rule in argument_map.items():
        if not isinstance(target_key, str) or not target_key:
            raise ToolError("alias argument_map keys must be non-empty strings")
        if isinstance(rule, str):
            mapped[target_key] = _source_arg(args, rule, target_key)
            continue
        if not isinstance(rule, dict):
            raise ToolError(f"alias rule for {target_key} must be a string or object")
        if "const" in rule:
            mapped[target_key] = rule["const"]
            continue
        source_key = rule.get("from")
        if not isinstance(source_key, str) or not source_key:
            raise ToolError(f"alias rule for {target_key} requires from or const")
        if source_key in args:
            mapped[target_key] = args[source_key]
        elif "default" in rule:
            mapped[target_key] = rule["default"]
        else:
            raise ToolError(f"missing alias source argument: {source_key}")
    return mapped


def _source_arg(args: dict[str, Any], source_key: str, target_key: str) -> Any:
    if source_key not in args:
        raise ToolError(f"missing alias source argument for {target_key}: {source_key}")
    return args[source_key]
