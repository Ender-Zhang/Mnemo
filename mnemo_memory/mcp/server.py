from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from .. import __version__
from ..core.config import DEFAULT_STATE_DIR
from ..core.jsonutil import dumps
from ..sdk import MemoryClient


MCP_PROTOCOL_VERSION = "2024-11-05"


class MemoryMcpServer:
    def __init__(self, *, state_dir: str | Path = DEFAULT_STATE_DIR) -> None:
        self.state_dir = str(state_dir)
        self.client = MemoryClient(state_dir=self.state_dir)

    def tools(self) -> list[dict[str, Any]]:
        return mcp_tool_descriptors()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        handlers = {
            "mnemo_memory_context": lambda: self.client.context(
                _string(args.get("intent")),
                limit=_int(args.get("limit"), 8),
                scope=_string(args.get("scope"), "memory"),
            ),
            "mnemo_memory_recall": lambda: self.client.recall(
                _required(args.get("seed"), "seed"),
                context=_string(args.get("context")),
                depth=_int(args.get("depth"), 2),
                limit=_int(args.get("limit"), 8),
            ),
            "mnemo_memory_search": lambda: self.client.search(
                _required(args.get("query"), "query"),
                limit=_int(args.get("limit"), 8),
                scope=_string(args.get("scope"), "memory"),
                include_tombstoned=bool(args.get("include_tombstoned", False)),
            ),
            "mnemo_memory_update": lambda: self.client.update(
                facts=_list(args.get("facts")),
                observations=_list(args.get("observations")),
                source=_string(args.get("source"), "mcp"),
                run_id=_optional(args.get("run_id")),
                mission_id=_optional(args.get("mission_id")),
            ),
            "mnemo_memory_read": lambda: self.client.read(_required(args.get("memory_id"), "memory_id")),
            "mnemo_memory_links": lambda: self.client.links(
                _required(args.get("memory_id"), "memory_id"),
                direction=_string(args.get("direction"), "both"),
            ),
            "mnemo_memory_provenance": lambda: self.client.provenance(_required(args.get("memory_id"), "memory_id")),
            "mnemo_memory_snapshot": lambda: self.client.snapshot(
                compile=bool(args.get("compile", False)),
                limit=_int(args.get("limit"), 50),
            ),
            "mnemo_memory_health": lambda: self.client.health(limit=_int(args.get("limit"), 20)),
            "mnemo_memory_tombstones": lambda: self.client.tombstones(
                target_id=_optional(args.get("target_id")),
                target_type=_optional(args.get("target_type")),
                limit=_int(args.get("limit"), 50),
            ),
            "mnemo_memory_promote_candidate": lambda: self.client.promote_candidate(
                _required(args.get("candidate_id"), "candidate_id"),
                min_confidence=_float(args.get("min_confidence"), 0.7),
            ),
            "mnemo_memory_reject_candidate": lambda: self.client.reject_candidate(
                _required(args.get("candidate_id"), "candidate_id"),
                _required(args.get("reason"), "reason"),
            ),
            "mnemo_memory_tombstone": lambda: self.client.tombstone(
                _required(args.get("memory_id"), "memory_id"),
                _required(args.get("reason"), "reason"),
                target_type=_string(args.get("target_type"), "auto"),
                replacement_id=_optional(args.get("replacement_id")),
            ),
            "mnemo_memory_forget": lambda: self.client.forget(
                _required(args.get("memory_id"), "memory_id"),
                reason=_string(args.get("reason"), "private_delete"),
                target_type=_string(args.get("target_type"), "auto"),
            ),
            "mnemo_memory_dream_run": lambda: self.client.dream_run(
                limit=_int(args.get("limit"), 20),
                min_confidence=_float(args.get("min_confidence"), 0.7),
                actions=_list(args.get("actions")) or None,
                use_provider=bool(args.get("use_provider", False)),
            ),
            "mnemo_memory_dream_status": lambda: self.client.dream_status(limit=_int(args.get("limit"), 20)),
        }
        handler = handlers.get(name)
        if handler is None:
            raise ValueError(f"unknown MCP tool: {name}")
        return handler()

    def call_tool_result(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self.call_tool(name, arguments)
        return {
            "content": [{"type": "text", "text": dumps(payload)}],
            "structuredContent": payload,
            "isError": False,
        }

    def handle_json_rpc(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        try:
            if method == "initialize":
                return _json_rpc_result(
                    request_id,
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "serverInfo": {"name": "mnemo-memory", "version": __version__},
                        "capabilities": {"tools": {}},
                    },
                )
            if method == "tools/list":
                return _json_rpc_result(request_id, {"tools": self.tools()})
            if method == "tools/call":
                params = message.get("params")
                if not isinstance(params, dict):
                    raise ValueError("tools/call params must be an object")
                return _json_rpc_result(
                    request_id,
                    self.call_tool_result(str(params.get("name") or ""), params.get("arguments") or {}),
                )
        except ValueError as exc:
            return _json_rpc_error(request_id, -32602, str(exc))
        except Exception as exc:  # pragma: no cover - protocol boundary
            return _json_rpc_error(request_id, -32000, str(exc))
        return _json_rpc_error(request_id, -32601, f"method not found: {method}")

    def serve_jsonl(self, *, input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> None:
        reader = input_stream or sys.stdin
        writer = output_stream or sys.stdout
        for line in reader:
            if not line.strip():
                continue
            try:
                response = self.handle_json_rpc(json.loads(line))
            except json.JSONDecodeError as exc:
                response = _json_rpc_error(None, -32700, f"parse error: {exc.msg}")
            if response is not None:
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
            message = _read_framed(reader)
            if message is None:
                break
            response = self.handle_json_rpc(message)
            if response is not None:
                _write_framed(writer, response)


def mcp_server_config(*, client: str = "generic", command: str = "mnemo-memory", state_dir: str | Path = DEFAULT_STATE_DIR) -> dict[str, Any]:
    server = {"command": command, "args": ["mcp", "serve", "--state-dir", str(state_dir)], "transport": "stdio"}
    if client == "claude":
        return {"mcpServers": {"mnemo-memory": server}}
    return {"name": "mnemo-memory", **server}


def mcp_tool_descriptors() -> list[dict[str, Any]]:
    return [
        _descriptor("mnemo_memory_context", "Return compact prompt-facing memory context.", {"intent": {"type": "string"}, "limit": {"type": "integer"}, "scope": {"type": "string"}}, read_only=True),
        _descriptor("mnemo_memory_recall", "Return associative memory recall cards.", {"seed": {"type": "string"}, "context": {"type": "string"}, "depth": {"type": "integer"}, "limit": {"type": "integer"}}, required=["seed"], read_only=True),
        _descriptor("mnemo_memory_search", "Search memory with query-plan metadata.", {"query": {"type": "string"}, "scope": {"type": "string"}, "limit": {"type": "integer"}, "include_tombstoned": {"type": "boolean"}}, required=["query"], read_only=True),
        _descriptor("mnemo_memory_update", "Write memory candidates and working notes.", {"facts": {"type": "array"}, "observations": {"type": "array"}, "source": {"type": "string"}, "run_id": {"type": ["string", "null"]}, "mission_id": {"type": ["string", "null"]}}, read_only=False),
        _descriptor("mnemo_memory_read", "Read one candidate or stable page.", {"memory_id": {"type": "string"}}, required=["memory_id"], read_only=True),
        _descriptor("mnemo_memory_links", "Read memory graph links.", {"memory_id": {"type": "string"}, "direction": {"type": "string"}}, required=["memory_id"], read_only=True),
        _descriptor("mnemo_memory_provenance", "Trace a memory item back to source candidates and observed events.", {"memory_id": {"type": "string"}}, required=["memory_id"], read_only=True),
        _descriptor("mnemo_memory_snapshot", "Read or compile the L1 memory snapshot.", {"compile": {"type": "boolean"}, "limit": {"type": "integer"}}, read_only=True),
        _descriptor("mnemo_memory_health", "Return compact memory health cards.", {"limit": {"type": "integer"}}, read_only=True),
        _descriptor("mnemo_memory_tombstones", "List compact tombstone records.", {"target_id": {"type": ["string", "null"]}, "target_type": {"type": ["string", "null"]}, "limit": {"type": "integer"}}, read_only=True),
        _descriptor("mnemo_memory_promote_candidate", "Promote a draft candidate through memory review guards.", {"candidate_id": {"type": "string"}, "min_confidence": {"type": "number"}}, required=["candidate_id"], read_only=False),
        _descriptor("mnemo_memory_reject_candidate", "Reject a candidate and record a tombstone.", {"candidate_id": {"type": "string"}, "reason": {"type": "string"}}, required=["candidate_id", "reason"], read_only=False),
        _descriptor("mnemo_memory_tombstone", "Tombstone an existing memory item.", {"memory_id": {"type": "string"}, "reason": {"type": "string"}, "target_type": {"type": "string"}, "replacement_id": {"type": ["string", "null"]}}, required=["memory_id", "reason"], read_only=False),
        _descriptor("mnemo_memory_forget", "Private-delete and redact a memory item.", {"memory_id": {"type": "string"}, "reason": {"type": "string"}, "target_type": {"type": "string"}}, required=["memory_id"], read_only=False),
        _descriptor("mnemo_memory_dream_run", "Run bounded memory-only Dream maintenance.", {"limit": {"type": "integer"}, "min_confidence": {"type": "number"}, "actions": {"type": "array"}, "use_provider": {"type": "boolean"}}, read_only=False),
        _descriptor("mnemo_memory_dream_status", "Return Dream backlog and latest report summary.", {"limit": {"type": "integer"}}, read_only=True),
    ]


def _descriptor(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
    read_only: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required or []},
        "annotations": {"readOnlyHint": read_only, "destructiveHint": False},
        "mnemo": {"risk": "read" if read_only else "write"},
    }


def _json_rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _json_rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _read_framed(reader: BinaryIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = reader.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, _, value = line.decode("ascii", errors="replace").partition(":")
        headers[key.casefold()] = value.strip()
    length = int(headers.get("content-length") or "0")
    if length <= 0:
        return None
    return json.loads(reader.read(length).decode("utf-8"))


def _write_framed(writer: BinaryIO, payload: dict[str, Any]) -> None:
    body = dumps(payload).encode("utf-8")
    writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    writer.flush()


def _required(value: Any, name: str) -> str:
    text = _string(value)
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional(value: Any) -> str | None:
    text = _string(value)
    return text or None


def _string(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None and str(value).strip() else default


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
