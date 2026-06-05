from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import socketserver
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..core.config import DEFAULT_STATE_DIR
from ..core.jsonutil import dumps
from ..sdk import MemoryClient, memory_api_schema


_WEB_ASSETS_DIR = Path(__file__).with_name("web_assets")


class _MemoryThreadingHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


@dataclass(frozen=True)
class MemoryWebConfig:
    state_dir: str | Path = DEFAULT_STATE_DIR
    host: str = "127.0.0.1"
    port: int = 8765
    # Kept for CLI/config compatibility; HTTP API access is currently open.
    auth_token: str | None = None


def build_http_server(config: MemoryWebConfig) -> ThreadingHTTPServer:
    handler = _handler(config)
    return _MemoryThreadingHTTPServer((config.host, int(config.port)), handler)


def serve_http(config: MemoryWebConfig) -> None:
    server = build_http_server(config)
    host, port = server.server_address
    print(f"mnemo-memory API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def dispatch_memory_api(client: MemoryClient, method: str, body: dict[str, Any]) -> dict[str, Any]:
    if method == "context":
        return client.context(
            str(body.get("intent") or ""),
            limit=int(body.get("limit") or 8),
            scope=str(body.get("scope") or "memory"),
        )
    if method == "recall":
        return client.recall(
            _required(body, "seed"),
            context=str(body.get("context") or ""),
            depth=int(body.get("depth") or 2),
            limit=int(body.get("limit") or 8),
        )
    if method == "search":
        return client.search(
            _required(body, "query"),
            limit=int(body.get("limit") or 8),
            scope=str(body.get("scope") or "memory"),
            include_tombstoned=bool(body.get("include_tombstoned", False)),
        )
    if method == "list":
        return client.list(
            kind=str(body.get("kind") or "all"),
            status=_optional(body.get("status")),
            limit=int(body.get("limit") or 50),
            include_tombstoned=bool(body.get("include_tombstoned", False)),
        )
    if method == "update":
        return client.update(
            facts=body.get("facts") if isinstance(body.get("facts"), list) else [],
            observations=body.get("observations") if isinstance(body.get("observations"), list) else [],
            source=str(body.get("source") or "http"),
            run_id=_optional(body.get("run_id")),
            mission_id=_optional(body.get("mission_id")),
        )
    if method == "ingest-event":
        return client.ingest_event(
            text=_required(body, "text"),
            source=str(body.get("source") or "http"),
            actor=_optional(body.get("actor")),
            event_type=str(body.get("event_type") or "message"),
            context=body.get("context") if isinstance(body.get("context"), list) else [],
            run_id=_optional(body.get("run_id")),
            mission_id=_optional(body.get("mission_id")),
            conversation_id=_optional(body.get("conversation_id")),
            message_id=_optional(body.get("message_id")),
            agent_id=_optional(body.get("agent_id")),
            event_at=body.get("event_at"),
            observed_at=body.get("observed_at"),
            scope=_optional(body.get("scope")),
            auto_promote=bool(body.get("auto_promote", False)),
            min_confidence=float(body.get("min_confidence") or 0.7),
            use_provider=bool(body.get("use_provider", False)),
        )
    if method == "read":
        return client.read(_required(body, "memory_id"))
    if method == "links":
        return client.links(_required(body, "memory_id"), direction=str(body.get("direction") or "both"))
    if method == "provenance":
        return client.provenance(_required(body, "memory_id"))
    if method == "snapshot":
        return client.snapshot(compile=bool(body.get("compile", False)), limit=int(body.get("limit") or 50))
    if method == "health":
        return client.health(limit=int(body.get("limit") or 20))
    if method == "tombstones":
        return client.tombstones(
            target_id=_optional(body.get("target_id")),
            target_type=_optional(body.get("target_type")),
            limit=int(body.get("limit") or 50),
        )
    if method == "promote-candidate":
        return client.promote_candidate(
            _required(body, "candidate_id"),
            min_confidence=float(body.get("min_confidence") or 0.7),
        )
    if method == "force-promote-candidate":
        return client.force_promote_candidate(_required(body, "candidate_id"))
    if method == "reject-candidate":
        return client.reject_candidate(_required(body, "candidate_id"), _required(body, "reason"))
    if method == "tombstone":
        return client.tombstone(
            _required(body, "memory_id"),
            _required(body, "reason"),
            target_type=str(body.get("target_type") or "auto"),
            replacement_id=_optional(body.get("replacement_id")),
        )
    if method == "forget":
        return client.forget(
            _required(body, "memory_id"),
            reason=str(body.get("reason") or "private_delete"),
            target_type=str(body.get("target_type") or "auto"),
        )
    if method == "dream-run":
        return client.dream_run(
            limit=int(body.get("limit") or 20),
            min_confidence=float(body.get("min_confidence") or 0.7),
            actions=body.get("actions") if isinstance(body.get("actions"), list) else None,
            use_provider=bool(body.get("use_provider", False)),
        )
    if method == "dream-status":
        return client.dream_status(limit=int(body.get("limit") or 20))
    if method == "dream-report":
        report = client.dream_report(_optional(body.get("report_id")), latest=bool(body.get("latest", False)))
        return {"kind": "dream_report_lookup", "report": report}
    raise KeyError(method)


def _handler(config: MemoryWebConfig):
    client = MemoryClient(state_dir=config.state_dir)

    class MemoryHandler(BaseHTTPRequestHandler):
        server_version = "MnemoMemory/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._send({"ok": True, "service": "mnemo-memory"})
                return
            if not parsed.path.startswith("/api/"):
                self._send_static(parsed.path)
                return
            if parsed.path == "/api/schema":
                self._send({"api_schema": memory_api_schema()})
                return
            if parsed.path == "/api/memory/read":
                query = parse_qs(parsed.query)
                memory_id = (query.get("memory_id") or [""])[0]
                self._dispatch("read", {"memory_id": memory_id})
                return
            self._send({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            prefix = "/api/memory/"
            if not parsed.path.startswith(prefix):
                self._send({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._dispatch(parsed.path.removeprefix(prefix), self._read_json())

        def _dispatch(self, method: str, body: dict[str, Any]) -> None:
            try:
                result = dispatch_memory_api(client, method, body)
            except KeyError:
                self._send({"error": f"unknown method: {method}"}, status=HTTPStatus.NOT_FOUND)
            except (TypeError, ValueError) as exc:
                self._send({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            else:
                self._send({"method": method, "result": result})

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            parsed = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("request body must be a JSON object")
            return parsed

        def _send(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = dumps(payload).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, raw_path: str) -> None:
            static_path = _resolve_static_path(raw_path)
            if static_path is None:
                self._send({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            body = static_path.read_bytes()
            content_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
            if static_path.name == "index.html":
                content_type = "text/html; charset=utf-8"
            elif content_type.startswith("text/") or content_type == "application/javascript":
                content_type = f"{content_type}; charset=utf-8"
            self.send_response(int(HTTPStatus.OK))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return MemoryHandler


def _required(body: dict[str, Any], key: str) -> str:
    value = str(body.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _resolve_static_path(raw_path: str) -> Path | None:
    path = unquote(raw_path or "/")
    if "\\" in path:
        return None
    try:
        assets_root = _WEB_ASSETS_DIR.resolve(strict=False)
    except OSError:
        return None

    if path in {"", "/"}:
        return _existing_index(assets_root)

    if path.startswith("/assets/"):
        candidate = (assets_root / "assets" / path.removeprefix("/assets/")).resolve(strict=False)
        if not _is_relative_to(candidate, assets_root) or not candidate.is_file():
            return None
        return candidate

    if "." in Path(path).name:
        return None
    return _existing_index(assets_root)


def _existing_index(assets_root: Path) -> Path | None:
    index = assets_root / "index.html"
    return index if index.is_file() else None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
