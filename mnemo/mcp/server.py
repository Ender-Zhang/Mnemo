from __future__ import annotations

from copy import deepcopy
import json
import sys
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from .. import __version__
from ..core.config import DEFAULT_STATE_DIR
from ..core.jsonutil import dumps
from ..memory import MemoryEngine
from ..runtime import ScheduleService, scheduled_item_stats
from ..sdk import MnemoClient
from ..skills import SkillService, default_skill_roots
from ..storage import StateStore
from ..tools import ToolRegistry


MCP_PROTOCOL_VERSION = "2024-11-05"


class MnemoMcpServer:
    """Dependency-free MCP-style bridge over Mnemo's core API surfaces."""

    def __init__(
        self,
        *,
        state_dir: str | Path = DEFAULT_STATE_DIR,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.state_dir = str(state_dir)
        self.workspace_root = str(workspace_root) if workspace_root is not None else None
        self.client = MnemoClient(state_dir=self.state_dir, workspace_root=self.workspace_root)

    def tools(self) -> list[dict[str, Any]]:
        return mcp_tool_descriptors()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = _require_arguments(arguments)
        handlers = {
            "mnemo_context": self._context,
            "mnemo_capsule": self._capsule,
            "mnemo_update": self._update,
            "mnemo_recall": self._recall,
            "mnemo_search": self._search,
            "mnemo_skills": self._skills,
            "mnemo_tools": self._tools,
            "mnemo_watch": self._watch,
            "mnemo_cron": self._cron,
            "mnemo_run": self._run,
            "mnemo_replay": self._replay,
            "mnemo_eval": self._eval,
            "mnemo_runtime_status": self._runtime_status,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ValueError(f"unknown MCP tool: {name}")
        return handler(args)

    def call_tool_result(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self.call_tool(name, arguments)
        return _mcp_tool_result(payload)

    def handle_json_rpc(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return _json_rpc_error(None, -32600, "invalid request")
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params")
        try:
            if method == "initialize":
                return _json_rpc_result(request_id, _initialize_result())
            if method == "tools/list":
                return _json_rpc_result(request_id, {"tools": self.tools()})
            if method == "tools/call":
                if not isinstance(params, dict):
                    raise ValueError("tools/call params must be an object")
                name = params.get("name")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("tools/call requires a tool name")
                arguments = params.get("arguments") or {}
                return _json_rpc_result(request_id, self.call_tool_result(name.strip(), arguments))
        except ValueError as exc:
            return _json_rpc_error(request_id, -32602, str(exc))
        except Exception as exc:  # pragma: no cover - defensive protocol boundary
            return _json_rpc_error(request_id, -32000, str(exc))

        return _json_rpc_error(request_id, -32601, f"method not found: {method}")

    def serve_jsonl(
        self,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        reader = input_stream or sys.stdin
        writer = output_stream or sys.stdout
        for line in reader:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                response = _json_rpc_error(None, -32700, f"parse error: {exc.msg}")
            else:
                response = self.handle_json_rpc(message)
            if response is None:
                continue
            writer.write(dumps(response) + "\n")
            writer.flush()

    def serve_content_length(
        self,
        *,
        input_stream: BinaryIO | None = None,
        output_stream: BinaryIO | None = None,
    ) -> None:
        reader = input_stream or sys.stdin.buffer
        writer = output_stream or sys.stdout.buffer
        while True:
            try:
                message = _read_framed_json_rpc(reader)
            except _McpFrameError as exc:
                _write_framed_json_rpc(writer, _json_rpc_error(None, -32700, str(exc)))
                if not exc.recoverable:
                    break
                continue
            if message is None:
                break
            response = self.handle_json_rpc(message)
            if response is None:
                continue
            _write_framed_json_rpc(writer, response)

    def _context(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.context(
            _string(args.get("intent"), default=""),
            agent_role=_string(args.get("agent_role"), default="general"),
            budget_tokens=_bounded_int(args.get("budget_tokens"), default=4000, minimum=512, maximum=20000),
            include_associations=_bool(args.get("include_associations"), default=True),
            prompt_mode=_prompt_mode(args.get("prompt_mode"), default="full"),
        )

    def _capsule(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.capsule(
            _required_string(args.get("task"), "task"),
            runtime=_string(args.get("runtime"), default="external"),
            agent_type=_string(args.get("agent_type"), default="general"),
            requested_pages=_string_list(args.get("requested_pages")),
            allowed_pages=_string_list(args.get("allowed_pages")),
            conversation_id=_optional_string(args.get("conversation_id")),
            mission_id=_optional_string(args.get("mission_id")),
            limit=_bounded_int(args.get("limit"), default=8, minimum=1, maximum=50),
        )

    def _update(self, args: dict[str, Any]) -> dict[str, Any]:
        store = self._store()
        conversation_id, mission_id, run_id, created_run = _update_scope(store, args)
        source = _string(args.get("source"), default="mcp")
        memory = MemoryEngine(store)

        memory_candidates: list[dict[str, Any]] = []
        working_notes: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for fact in _list(args.get("facts")):
            normalized = _normalize_fact(fact)
            if not normalized["claim"]:
                skipped.append({"kind": "fact", "reason": "empty_claim"})
                continue
            result = memory.write_candidate(
                run_id,
                normalized["claim"],
                dimension=normalized["dimension"],
                scope=normalized["scope"],
                confidence=normalized["confidence"],
                evidence=[_update_evidence(source, fact)],
            )
            memory_candidates.append(
                {
                    "candidate_id": result["candidate_id"],
                    "status": result["status"],
                    "dimension": normalized["dimension"],
                    "scope": normalized["scope"],
                    "safety": result["safety"],
                }
            )

        for observation in _list(args.get("observations")):
            content, metadata = _normalize_observation(observation, source)
            if not content:
                skipped.append({"kind": "observation", "reason": "empty_content"})
                continue
            note_id = store.add_working_note(mission_id, run_id, content, metadata=metadata)
            working_notes.append({"note_id": note_id, "status": "open", "retention": metadata["retention"]})

        if created_run:
            store.complete_run(run_id, "MCP update recorded.", status="completed")

        return {
            "kind": "update_result",
            "version": "mnemo.update.v1",
            "conversation_id": conversation_id,
            "mission_id": mission_id,
            "run_id": run_id,
            "memory_candidates": memory_candidates,
            "working_notes": working_notes,
            "skipped": skipped,
        }

    def _recall(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.recall(
            _required_string(args.get("seed"), "seed"),
            depth=_bounded_int(args.get("depth"), default=2, minimum=1, maximum=4),
            context=_string(args.get("context"), default=""),
            limit=_bounded_int(args.get("limit"), default=8, minimum=1, maximum=20),
        )

    def _search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = _required_string(args.get("query"), "query")
        limit = _bounded_int(args.get("limit"), default=8, minimum=1, maximum=20)
        scope = _string(args.get("scope"), default="memory")
        memory = MemoryEngine(self._store())
        return {
            "kind": "memory_search_result",
            "version": "mnemo.search.v1",
            "query": query,
            "scope": scope,
            "query_plan": memory.plan_query(query).metadata(),
            "cards": memory.context_cards(query, limit=limit, search_scope=scope),
        }

    def _skills(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _bounded_int(args.get("limit"), default=12, minimum=1, maximum=50)
        query = _string(args.get("query"), default="").casefold()
        store = self._store()
        cards = SkillService(store, roots=default_skill_roots(self.state_dir)).context_cards(limit=max(limit, 50))
        if query:
            cards = [
                card
                for card in cards
                if query in str(card.get("name") or "").casefold()
                or query in str(card.get("description") or "").casefold()
                or query in str(card.get("source") or "").casefold()
            ]
        return {
            "kind": "skill_cards",
            "version": "mnemo.skills.v1",
            "cards": cards[:limit],
        }

    def _tools(self, args: dict[str, Any]) -> dict[str, Any]:
        profile = _string(args.get("profile"), default="full.v1")
        query = _string(args.get("query"), default="").casefold()
        risk = _string(args.get("risk"), default="")
        limit = _bounded_int(args.get("limit"), default=50, minimum=1, maximum=200)
        registry = ToolRegistry.from_store(self._store())
        bundle = registry.tool_bundle(profile=profile)
        cards = [
            {
                "name": spec.name,
                "description": spec.description,
                "risk": spec.risk,
            }
            for spec in bundle.specs
            if (not risk or spec.risk == risk)
            and (
                not query
                or query in spec.name.casefold()
                or query in spec.description.casefold()
                or query in spec.risk.casefold()
            )
        ]
        return {
            "kind": "tool_cards",
            "version": "mnemo.tools.v1",
            "bundle": bundle.metadata(),
            "cards": cards[:limit],
        }

    def _watch(self, args: dict[str, Any]) -> dict[str, Any]:
        item = ScheduleService(self.state_dir).add_watch(
            target=_required_string(args.get("target"), "target"),
            instruction=_string(args.get("instruction"), default=_string(args.get("target"), default="")),
            schedule=_string(args.get("schedule"), default="daily"),
            source=_string(args.get("source"), default="mcp"),
            next_run_at=args.get("next_run_at"),
            metadata={"source": "mcp"},
        )
        return {"kind": "scheduled_item", "version": "mnemo.watch.v1", "item": item}

    def _cron(self, args: dict[str, Any]) -> dict[str, Any]:
        item = ScheduleService(self.state_dir).add_cron(
            title=_optional_string(args.get("title")),
            message=_required_string(args.get("message"), "message"),
            schedule=_required_string(args.get("schedule"), "schedule"),
            source=_string(args.get("source"), default="mcp"),
            next_run_at=args.get("next_run_at"),
            metadata={"source": "mcp"},
        )
        return {"kind": "scheduled_item", "version": "mnemo.cron.v1", "item": item}

    def _run(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.run(
            _required_string(args.get("message"), "message"),
            conversation_id=_optional_string(args.get("conversation_id")),
            mission_id=_optional_string(args.get("mission_id")),
            prompt_mode=_prompt_mode(args.get("prompt_mode"), default="full"),
        )

    def _replay(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.replay(_required_string(args.get("run_id"), "run_id"))

    def _eval(self, args: dict[str, Any]) -> dict[str, Any]:
        variants = _string_list(args.get("variants"))
        return self.client.evaluate(
            _string(args.get("suite"), default="smoke"),
            variants=variants or None,
            release_gate=_bool(args.get("release_gate"), default=False),
        )

    def _runtime_status(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _bounded_int(args.get("limit"), default=10, minimum=1, maximum=50)
        store = self._store()
        inbox_items = store.list_inbox_items(status="open", limit=limit)
        generated_tools = store.list_generated_tools(status=None, limit=100)
        return {
            "kind": "runtime_status",
            "version": "mnemo.runtime_status.v1",
            "queue": store.queue_stats(),
            "recent_runs": [
                _run_status_card(run)
                for run in store.list_runs(limit=limit)
            ],
            "open_inbox": {
                "count": len(inbox_items),
                "items": [_inbox_card(item) for item in inbox_items],
            },
            "generated_tools": _status_counts(generated_tools),
            "scheduled": scheduled_item_stats(store),
        }

    def _store(self) -> StateStore:
        store = StateStore(self.state_dir)
        store.initialize()
        return store


def mcp_tool_descriptors() -> list[dict[str, Any]]:
    return deepcopy(_TOOL_DESCRIPTORS)


class _McpFrameError(ValueError):
    def __init__(self, message: str, *, recoverable: bool) -> None:
        super().__init__(message)
        self.recoverable = recoverable


def _read_framed_json_rpc(reader: BinaryIO) -> dict[str, Any] | None:
    header = bytearray()
    while not header.endswith(b"\r\n\r\n"):
        chunk = reader.read(1)
        if not chunk:
            if not header:
                return None
            raise _McpFrameError("truncated MCP frame header", recoverable=False)
        header.extend(chunk)
        if len(header) > 32_768:
            raise _McpFrameError("MCP frame header too large", recoverable=False)

    try:
        header_text = bytes(header[:-4]).decode("ascii")
    except UnicodeDecodeError as exc:
        raise _McpFrameError("MCP frame header must be ASCII", recoverable=False) from exc

    content_length: int | None = None
    for line in header_text.split("\r\n"):
        if not line:
            continue
        name, separator, value = line.partition(":")
        if not separator:
            raise _McpFrameError("malformed MCP frame header", recoverable=False)
        if name.strip().casefold() == "content-length":
            try:
                content_length = int(value.strip())
            except ValueError as exc:
                raise _McpFrameError("invalid Content-Length header", recoverable=False) from exc

    if content_length is None:
        raise _McpFrameError("missing Content-Length header", recoverable=False)
    if content_length <= 0:
        raise _McpFrameError("invalid Content-Length header", recoverable=False)

    body = reader.read(content_length)
    if len(body) != content_length:
        raise _McpFrameError("truncated MCP frame body", recoverable=False)

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _McpFrameError("MCP frame body must be UTF-8 JSON", recoverable=True) from exc

    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _McpFrameError(f"parse error: {exc.msg}", recoverable=True) from exc
    if not isinstance(message, dict):
        raise _McpFrameError("MCP frame body must be a JSON object", recoverable=True)
    return message


def _write_framed_json_rpc(writer: BinaryIO, message: dict[str, Any]) -> None:
    payload = dumps(message).encode("utf-8")
    writer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
    writer.write(payload)
    writer.flush()


def _schema(
    properties: dict[str, dict[str, Any]],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _descriptor(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    *,
    risk: str,
    read_only: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": False,
        },
        "mnemo": {
            "risk": risk,
        },
    }


_TOOL_DESCRIPTORS = [
    _descriptor(
        "mnemo_context",
        "Return a prompt-ready compact context block for an external agent turn.",
        _schema(
            {
                "intent": {"type": "string", "default": ""},
                "agent_role": {"type": "string", "default": "general"},
                "budget_tokens": {"type": "integer", "minimum": 512, "maximum": 20000, "default": 4000},
                "include_associations": {"type": "boolean", "default": True},
                "prompt_mode": {"type": "string", "enum": ["full", "minimal", "capsule"], "default": "full"},
            }
        ),
        risk="read",
        read_only=True,
    ),
    _descriptor(
        "mnemo_capsule",
        "Build a minimal-disclosure context capsule for an external runtime handoff.",
        _schema(
            {
                "task": {"type": "string"},
                "runtime": {"type": "string", "default": "external"},
                "agent_type": {"type": "string", "default": "general"},
                "requested_pages": {"type": "array", "items": {"type": "string"}},
                "allowed_pages": {"type": "array", "items": {"type": "string"}},
                "conversation_id": {"type": ["string", "null"]},
                "mission_id": {"type": ["string", "null"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
            },
            required=["task"],
        ),
        risk="read",
        read_only=True,
    ),
    _descriptor(
        "mnemo_update",
        "Write memory candidates and working notes from an external execution trajectory.",
        _schema(
            {
                "facts": {"type": "array", "items": {"type": ["object", "string"]}, "default": []},
                "observations": {"type": "array", "items": {"type": ["object", "string"]}, "default": []},
                "source": {"type": "string", "default": "mcp"},
                "conversation_id": {"type": ["string", "null"]},
                "mission_id": {"type": ["string", "null"]},
                "run_id": {"type": ["string", "null"]},
            }
        ),
        risk="write",
        read_only=False,
    ),
    _descriptor(
        "mnemo_recall",
        "Return compact associative recall cards from memory and prior session snippets.",
        _schema(
            {
                "seed": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2},
                "context": {"type": "string", "default": ""},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            required=["seed"],
        ),
        risk="read",
        read_only=True,
    ),
    _descriptor(
        "mnemo_search",
        "Search memory and session snippets with compact cards and query-plan metadata.",
        _schema(
            {
                "query": {"type": "string"},
                "scope": {"type": "string", "enum": ["memory", "stable", "sessions", "all"], "default": "memory"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            required=["query"],
        ),
        risk="read",
        read_only=True,
    ),
    _descriptor(
        "mnemo_skills",
        "List available skills as compact cards.",
        _schema(
            {
                "query": {"type": "string", "default": ""},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 12},
            }
        ),
        risk="read",
        read_only=True,
    ),
    _descriptor(
        "mnemo_tools",
        "List available tool cards without returning raw provider schemas.",
        _schema(
            {
                "query": {"type": "string", "default": ""},
                "risk": {"type": "string", "enum": ["", "read", "write", "external", "admin"], "default": ""},
                "profile": {"type": "string", "enum": ["full.v1", "minimal.v1", "capsule.v1", "learning.v1"], "default": "full.v1"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            }
        ),
        risk="read",
        read_only=True,
    ),
    _descriptor(
        "mnemo_watch",
        "Register a durable watch that enqueues model-led checks when due.",
        _schema(
            {
                "target": {"type": "string"},
                "instruction": {"type": "string"},
                "schedule": {"type": "string", "default": "daily"},
                "next_run_at": {"type": ["string", "number", "null"]},
                "source": {"type": "string", "default": "mcp"},
            },
            required=["target"],
        ),
        risk="write",
        read_only=False,
    ),
    _descriptor(
        "mnemo_cron",
        "Register a durable scheduled Mnemo task that enqueues normal runs when due.",
        _schema(
            {
                "schedule": {"type": "string"},
                "message": {"type": "string"},
                "title": {"type": "string"},
                "next_run_at": {"type": ["string", "number", "null"]},
                "source": {"type": "string", "default": "mcp"},
            },
            required=["schedule", "message"],
        ),
        risk="write",
        read_only=False,
    ),
    _descriptor(
        "mnemo_run",
        "Execute one native Mnemo turn through the existing runtime harness.",
        _schema(
            {
                "message": {"type": "string"},
                "conversation_id": {"type": ["string", "null"]},
                "mission_id": {"type": ["string", "null"]},
                "prompt_mode": {"type": "string", "enum": ["full", "minimal", "capsule"], "default": "full"},
            },
            required=["message"],
        ),
        risk="write",
        read_only=False,
    ),
    _descriptor(
        "mnemo_replay",
        "Summarize a persisted run trace for debugging and replay.",
        _schema({"run_id": {"type": "string"}}, required=["run_id"]),
        risk="read",
        read_only=True,
    ),
    _descriptor(
        "mnemo_eval",
        "Run a deterministic Mnemo eval suite, variant comparison, or release gate and return a compact report.",
        _schema(
            {
                "suite": {"type": "string", "default": "smoke"},
                "release_gate": {"type": "boolean", "default": False},
                "variants": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["no_memory", "skills_only", "full_mnemo"]},
                },
            }
        ),
        risk="read",
        read_only=True,
    ),
    _descriptor(
        "mnemo_runtime_status",
        "Return compact queue, run, inbox, and generated-tool status.",
        _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}}),
        risk="read",
        read_only=True,
    ),
]


def _mcp_tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": dumps(payload)}],
        "structuredContent": payload,
        "isError": False,
    }


def _initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {"name": "mnemo", "version": __version__},
        "capabilities": {"tools": {}},
    }


def _json_rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _json_rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _require_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    return arguments


def _update_scope(store: StateStore, args: dict[str, Any]) -> tuple[str, str, str, bool]:
    run_id = _optional_string(args.get("run_id"))
    conversation_id = _optional_string(args.get("conversation_id"))
    mission_id = _optional_string(args.get("mission_id"))
    if run_id:
        run = store.get_run(run_id)
        if not run:
            raise ValueError(f"run not found: {run_id}")
        return str(run["conversation_id"]), str(run["mission_id"]), run_id, False

    if mission_id:
        mission = store.get_mission(mission_id)
        if not mission:
            raise ValueError(f"mission not found: {mission_id}")
        conversation_id = str(mission["conversation_id"])
    if not conversation_id:
        conversation_id = store.create_conversation("MCP updates")
    if not mission_id:
        mission_id = store.create_mission(conversation_id, "MCP external updates")
    run_id = store.create_run(conversation_id, mission_id, "MCP external update")
    return conversation_id, mission_id, run_id, True


def _normalize_fact(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {
            "claim": _normalize_space(value),
            "dimension": "external_update",
            "scope": "global",
            "confidence": 0.6,
        }
    if not isinstance(value, dict):
        return {"claim": "", "dimension": "external_update", "scope": "global", "confidence": 0.6}
    claim = _normalize_space(value.get("claim") or value.get("text") or value.get("content") or "")
    return {
        "claim": claim,
        "dimension": _string(value.get("dimension"), default="external_update"),
        "scope": _string(value.get("scope"), default="global"),
        "confidence": _bounded_float(value.get("confidence"), default=0.6, minimum=0.0, maximum=1.0),
    }


def _normalize_observation(value: Any, source: str) -> tuple[str, dict[str, Any]]:
    if isinstance(value, str):
        return _normalize_space(value), {"source": source, "retention": "ephemeral"}
    if not isinstance(value, dict):
        return "", {"source": source, "retention": "ephemeral"}
    content = _normalize_space(value.get("content") or value.get("text") or value.get("summary") or "")
    retention = _string(value.get("retention"), default="ephemeral")
    if retention not in {"ephemeral", "memory_candidate"}:
        retention = "ephemeral"
    return (
        content,
        {
            "source": source,
            "retention": retention,
            "dimension": _string(value.get("dimension"), default="observation"),
            "scope": _string(value.get("scope"), default="mission"),
            "confidence": _bounded_float(value.get("confidence"), default=0.62, minimum=0.0, maximum=1.0),
        },
    )


def _update_evidence(source: str, raw: Any) -> dict[str, Any]:
    evidence = {"kind": "mcp_update", "source": source}
    if isinstance(raw, dict):
        for key in ("run_id", "url", "path", "tool", "event_id"):
            if raw.get(key):
                evidence[key] = raw[key]
    return evidence


def _deferred_surface(kind: str, args: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "kind": f"{kind}_surface",
        "status": "not_implemented",
        "reason": reason,
        "requested": _compact_mapping(args),
    }


def _run_status_card(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run.get("id"),
        "conversation_id": run.get("conversation_id"),
        "mission_id": run.get("mission_id"),
        "status": run.get("status"),
        "input": _truncate(run.get("input_text"), limit=120),
        "created_at": run.get("created_at"),
        "completed_at": run.get("completed_at"),
    }


def _inbox_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "priority": item.get("priority"),
        "category": item.get("category"),
        "title": item.get("title"),
        "action_type": item.get("action_type"),
        "source_run_id": item.get("source_run_id"),
        "created_at": item.get("created_at"),
    }


def _status_counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(items), "counts": counts}


def _compact_mapping(value: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, str):
            compact[key] = _truncate(item, limit=180)
        elif isinstance(item, (int, float, bool)) or item is None:
            compact[key] = item
        elif isinstance(item, list):
            compact[key] = {"count": len(item)}
        elif isinstance(item, dict):
            compact[key] = {"keys": sorted(str(k) for k in item)[:20]}
        else:
            compact[key] = str(type(item).__name__)
    return compact


def _prompt_mode(value: Any, *, default: str) -> str:
    mode = _string(value, default=default)
    if mode not in {"full", "minimal", "capsule"}:
        raise ValueError(f"invalid prompt_mode: {mode}")
    return mode


def _required_string(value: Any, name: str) -> str:
    text = _string(value, default="")
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = _string(value, default="")
    return text or None


def _string(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in _list(value):
        for part in str(item).split(","):
            text = part.strip()
            if text:
                result.append(text)
    return result


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def _truncate(value: Any, *, limit: int) -> str:
    text = _normalize_space(value)
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."
