from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
import json
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ..core.config import DEFAULT_MAX_TOOL_ROUNDS
from ..core.events import chat_event_as_dict
from ..core.errors import MnemoError
from ..core.jsonutil import dumps
from ..core.models import RunRequest
from ..core.settings import load_user_settings, save_user_settings, settings_path
from ..core.workspace import resolve_workspace_root
from ..channels import (
    FeishuQrOnboardSession,
    feishu_channel_status,
    poll_feishu_qr_onboarding,
    start_feishu_qr_onboarding,
)
from ..providers import AnthropicProviderAdapter, OpenAIProviderAdapter, ProviderConfig
from ..runtime import run_dream_with_provider, run_local, run_provider, stream_local, stream_provider
from ..runtime.approvals import resolve_inbox_item_with_actions
from ..runtime.ledger import RunLedger
from ..runtime.proactive import ProactiveService, proactive_status
from ..runtime.scheduler import DEFAULT_DREAM_LIMIT, ScheduleService, ensure_default_dream_schedule
from ..memory import MemoryEngine
from ..memory.wiki import materialize_memory_page, memory_page_wiki_path, memory_page_wiki_ref
from ..memory.query import MEMORY_ONTOLOGY_DIMENSIONS, is_known_memory_dimension, normalize_memory_dimension
from ..sdk import MnemoClient, mnemo_core_api_schema
from ..skills import SkillService, default_skill_roots
from ..storage import StateStore
from ..tools import ToolRegistry


@dataclass(frozen=True)
class WebServerConfig:
    state_dir: str
    host: str = "127.0.0.1"
    port: int = 8765
    workspace_root: str | None = None
    provider: str = "local"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    timeout_s: float = 30.0
    retry_count: int = 0
    retry_backoff_s: float = 0.0
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS


@dataclass(frozen=True)
class WebAuthConfig:
    enabled: bool
    password_hash: str = ""
    session_key: bytes = b""


_ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
_AUTH_COOKIE_NAME = "mnemo_web_session"
_AUTH_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
_AUTH_PASSWORD_ENV = "MNEMO_WEB_PASSWORD"
_AUTH_PASSWORD_HASH_ENV = "MNEMO_WEB_PASSWORD_SHA256"
_AUTO_DREAM_TICK_INTERVAL_SECONDS = 300.0

_MEMORY_DIMENSION_LABELS = {
    "identity": "身份",
    "cognition": "认知",
    "values": "价值",
    "goals": "目标",
    "preferences": "偏好",
    "relationships": "关系",
    "context": "语境",
    "history": "历史",
    "patterns": "模式",
    "boundaries": "边界",
}

_MEMORY_EVIDENCE_LABELS = {
    "source_candidate": "来源候选",
    "turn": "对话",
    "tool": "工具",
    "tombstone": "归档记录",
    "memory_safety": "安全检查",
}

def build_http_server(config: WebServerConfig) -> ThreadingHTTPServer:
    StateStore(config.state_dir).initialize()
    config = _resolved_web_config(config)
    handler = _handler_for(config)
    return MnemoHTTPServer((config.host, config.port), handler)


class MnemoHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self) -> None:
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name = str(self.server_address[0])
        self.server_port = int(self.server_address[1])


def serve_web(config: WebServerConfig) -> None:
    config = _resolved_web_config(config)
    server = build_http_server(config)
    auto_dream = _AutoDreamScheduler(config)
    proactive = _ProactiveScheduler(config)
    auto_dream.start()
    proactive.start()
    host, port = server.server_address
    print(f"Mnemo web listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        proactive.stop()
        auto_dream.stop()
        server.server_close()


def serve_api(config: WebServerConfig) -> None:
    server = build_http_server(config)
    host, port = server.server_address
    print(f"Mnemo core API listening on http://{host}:{port}/api/core")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _resolved_web_config(config: WebServerConfig) -> WebServerConfig:
    workspace_root = resolve_workspace_root(config.workspace_root, config.state_dir)
    workspace_root.mkdir(parents=True, exist_ok=True)
    return WebServerConfig(
        state_dir=config.state_dir,
        host=config.host,
        port=config.port,
        workspace_root=str(workspace_root),
        provider=config.provider,
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key,
        api_key_env=config.api_key_env,
        timeout_s=config.timeout_s,
        retry_count=config.retry_count,
        retry_backoff_s=config.retry_backoff_s,
        max_tool_rounds=config.max_tool_rounds,
    )


def _handler_for(config: WebServerConfig) -> type[BaseHTTPRequestHandler]:
    feishu_onboard_sessions: dict[str, FeishuQrOnboardSession] = {}
    feishu_onboard_lock = threading.Lock()
    auth_config = _web_auth_config()

    class Handler(BaseHTTPRequestHandler):
        server_version = "MnemoWeb/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                effective = _effective_web_config(config)
                self._send_json({"ok": True, "provider": effective.provider, "model": effective.model or ""})
                return
            if parsed.path == "/api/auth/session":
                self._send_json(
                    {"auth_required": auth_config.enabled, "authenticated": self._is_authenticated(auth_config)}
                )
                return
            if parsed.path == "/login":
                self._send_login_page()
                return
            if auth_config.enabled and not self._is_authenticated(auth_config):
                self._send_auth_required(parsed.path)
                return
            if parsed.path == "/":
                self._send_asset("index.html", "text/html; charset=utf-8")
            elif parsed.path == "/app.css":
                self._send_asset("app.css", "text/css; charset=utf-8")
            elif parsed.path == "/app.js":
                self._send_asset("app.js", "application/javascript; charset=utf-8")
            elif parsed.path == "/api/core/schema":
                self._send_json({"api_schema": mnemo_core_api_schema()})
            elif parsed.path == "/api/core/openapi.json":
                self._send_json(_core_openapi_schema())
            elif parsed.path == "/api/events":
                self._handle_events(parsed.query)
            elif parsed.path == "/api/artifacts":
                self._handle_artifact(parsed.query)
            elif parsed.path == "/api/inbox":
                self._handle_inbox(parsed.query)
            elif parsed.path == "/api/settings":
                self._handle_settings()
            elif parsed.path == "/api/channels/feishu":
                self._handle_feishu_channel_status()
            elif parsed.path == "/api/catalog":
                self._handle_catalog()
            elif parsed.path == "/api/memory/ontology":
                self._handle_memory_ontology()
            elif parsed.path == "/api/memory/dimension":
                self._handle_memory_dimension(parsed.query)
            elif parsed.path == "/api/memory/item":
                self._handle_memory_item(parsed.query)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/auth/login":
                self._handle_auth_login(auth_config)
                return
            if parsed.path == "/api/auth/logout":
                self._handle_auth_logout()
                return
            if auth_config.enabled and not self._is_authenticated(auth_config):
                self._send_json({"error": "authentication required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            if parsed.path == "/api/chat":
                self._handle_chat()
            elif parsed.path.startswith("/api/core/"):
                self._handle_core_api(parsed.path)
            elif parsed.path == "/api/runs/cancel":
                self._handle_run_cancel()
            elif parsed.path == "/api/inbox/resolve":
                self._handle_inbox_resolve()
            elif parsed.path == "/api/learning/memory":
                self._handle_learning_memory()
            elif parsed.path == "/api/settings":
                self._handle_settings_update()
            elif parsed.path == "/api/channels/feishu/onboard/start":
                self._handle_feishu_onboard_start()
            elif parsed.path == "/api/channels/feishu/onboard/poll":
                self._handle_feishu_onboard_poll()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def _handle_auth_login(self, auth: WebAuthConfig) -> None:
            if not auth.enabled:
                self._send_json({"auth_required": False, "authenticated": True})
                return
            try:
                body = self._read_json_body()
                password = _required_string(body, "password")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if not _web_password_matches(auth, password):
                self._send_json({"error": "invalid password"}, status=HTTPStatus.UNAUTHORIZED)
                return
            self._send_json(
                {"auth_required": True, "authenticated": True},
                headers={"Set-Cookie": _auth_cookie_header(auth)},
            )

        def _handle_auth_logout(self) -> None:
            self._send_json(
                {"authenticated": False},
                headers={"Set-Cookie": f"{_AUTH_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"},
            )

        def _is_authenticated(self, auth: WebAuthConfig) -> bool:
            if not auth.enabled:
                return True
            return _auth_cookie_is_valid(auth, str(self.headers.get("Cookie") or ""))

        def _send_auth_required(self, path: str) -> None:
            if path.startswith("/api/"):
                self._send_json({"error": "authentication required"}, status=HTTPStatus.UNAUTHORIZED)
                return
            self._send_login_page(status=HTTPStatus.OK if path in {"", "/"} else HTTPStatus.UNAUTHORIZED)

        def _send_login_page(self, status: HTTPStatus = HTTPStatus.OK) -> None:
            content = _login_page_html().encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)

        def _handle_chat(self) -> None:
            try:
                body = self._read_json_body()
                message = _required_string(body, "message")
                request = RunRequest(
                    message=message,
                    state_dir=config.state_dir,
                    conversation_id=_optional_string(body.get("conversation_id")),
                    mission_id=_optional_string(body.get("mission_id")),
                    workspace_root=config.workspace_root,
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            emitted_stream_error = False
            try:
                for event in _stream_events(config, request):
                    if event.type.endswith(".error"):
                        emitted_stream_error = True
                    self._write_ndjson(chat_event_as_dict(event))
            except Exception as exc:
                if not emitted_stream_error:
                    self._write_ndjson({"type": "server.error", "data": {"error": str(exc)}})
            finally:
                try:
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                self.close_connection = True

        def _handle_run_cancel(self) -> None:
            try:
                body = self._read_json_body()
                run_id = _required_string(body, "run_id")
                reason = _optional_string(body.get("reason")) or "cancelled"
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            store = StateStore(config.state_dir)
            store.initialize()
            try:
                result = store.cancel_run(run_id, reason=reason)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return

            store.append_event(
                run_id,
                "run.cancel.requested",
                {"reason": reason, "changed": result["changed"], "status": result["status"], "source": "web"},
            )
            self._send_json({"run_id": run_id, "status": result["status"], "changed": result["changed"]})

        def _handle_events(self, query: str) -> None:
            params = parse_qs(query)
            run_id = _first_param(params, "run_id")
            if not run_id:
                self._send_json({"error": "run_id is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            since = _int_param(params, "since", 0)
            since_event_id = _first_param(params, "sinceEventId")
            chat_only = _bool_param(params, "chat", True)
            store = StateStore(config.state_dir)
            store.initialize()
            ledger = RunLedger(store)
            if chat_only and since_event_id:
                events = ledger.chat_events_after_event_id(run_id, since_event_id)
            elif chat_only:
                events = ledger.chat_events(run_id, since=since)
            else:
                events = ledger.events_since(run_id, since=since)
            self._send_json({"events": events, "last_event_id": _last_chat_event_id(events)})

        def _handle_artifact(self, query: str) -> None:
            params = parse_qs(query)
            artifact_id = _first_param(params, "artifact_id")
            if not artifact_id:
                self._send_json({"error": "artifact_id is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            store = StateStore(config.state_dir)
            store.initialize()
            artifact = store.get_artifact(artifact_id)
            if not artifact:
                self._send_json({"error": "artifact not found"}, status=HTTPStatus.NOT_FOUND)
                return
            related = []
            if artifact.get("mission_id"):
                related = [
                    item
                    for item in store.list_artifacts(mission_id=artifact.get("mission_id"), limit=20)
                    if item.get("id") != artifact_id
                ]
            self._send_json({"artifact": artifact, "related": related})

        def _handle_inbox(self, query: str) -> None:
            params = parse_qs(query)
            status = _first_param(params, "status") or "open"
            category = _first_param(params, "category")
            limit = _int_param(params, "limit", 50)
            store = StateStore(config.state_dir)
            store.initialize()
            try:
                priority = _priority_lte(_first_param(params, "priority"))
                items = store.list_inbox_items(
                    status=None if status == "all" else status,
                    category=category,
                    priority_lte=priority,
                    limit=limit,
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"items": items})

        def _handle_settings(self) -> None:
            self._send_json(_settings_payload(config))

        def _handle_feishu_channel_status(self) -> None:
            self._send_json({"feishu": feishu_channel_status(config.state_dir)})

        def _handle_catalog(self) -> None:
            self._send_json(_catalog_payload(config))

        def _handle_memory_ontology(self) -> None:
            self._send_json(_memory_ontology_payload(config))

        def _handle_memory_dimension(self, query: str) -> None:
            params = parse_qs(query)
            raw_dimension = _first_param(params, "dimension")
            if not raw_dimension:
                self._send_json({"error": "dimension is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not is_known_memory_dimension(raw_dimension):
                self._send_json({"error": f"unknown memory dimension: {raw_dimension}"}, status=HTTPStatus.BAD_REQUEST)
                return
            dimension = normalize_memory_dimension(raw_dimension, fallback="context")
            self._send_json(_memory_dimension_payload(config, dimension))

        def _handle_memory_item(self, query: str) -> None:
            params = parse_qs(query)
            item_type = _first_param(params, "type")
            item_id = _first_param(params, "id")
            if not item_type:
                self._send_json({"error": "type is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not item_id:
                self._send_json({"error": "id is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = _memory_item_payload(config, item_type, item_id)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if payload is None:
                self._send_json({"error": f"memory item not found: {item_id}"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)

        def _handle_settings_update(self) -> None:
            try:
                body = self._read_json_body()
                save_user_settings(config.state_dir, body)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(_settings_payload(config))

        def _handle_feishu_onboard_start(self) -> None:
            try:
                body = self._read_json_body()
                domain = _optional_string(body.get("domain")) or "feishu"
                session = start_feishu_qr_onboarding(domain=domain)
            except (ValueError, MnemoError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            with feishu_onboard_lock:
                feishu_onboard_sessions[session.session_id] = session
            self._send_json({"status": "pending", "session": session.public_dict(), "feishu": feishu_channel_status(config.state_dir)})

        def _handle_feishu_onboard_poll(self) -> None:
            try:
                body = self._read_json_body()
                session_id = _required_string(body, "session_id")
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            with feishu_onboard_lock:
                session = feishu_onboard_sessions.get(session_id)
            if session is None:
                self._send_json({"error": f"Feishu onboarding session not found: {session_id}"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                result = poll_feishu_qr_onboarding(session, state_dir=config.state_dir, save=True)
            except MnemoError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if result.get("status") in {"configured", "denied", "expired"}:
                with feishu_onboard_lock:
                    feishu_onboard_sessions.pop(session_id, None)
            self._send_json(result)

        def _handle_inbox_resolve(self) -> None:
            try:
                body = self._read_json_body()
                item_id = _required_string(body, "item_id")
                resolution = _required_string(body, "resolution")
                notes = _optional_string(body.get("notes"))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            store = StateStore(config.state_dir)
            store.initialize()
            try:
                result = resolve_inbox_item_with_actions(
                    store,
                    item_id,
                    resolution,
                    notes=notes,
                    workspace_root=config.workspace_root,
                    source="web",
                )
            except ValueError as exc:
                message = str(exc)
                status = HTTPStatus.NOT_FOUND if "not found" in message else HTTPStatus.BAD_REQUEST
                self._send_json({"error": message}, status=status)
                return
            self._send_json(result)

        def _handle_learning_memory(self) -> None:
            try:
                body = self._read_json_body()
                candidate_id = _required_string(body, "candidate_id")
                action = _learning_action(_required_string(body, "action"))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            store = StateStore(config.state_dir)
            store.initialize()
            candidate = store.get_memory_candidate(candidate_id)
            if not candidate:
                self._send_json({"error": f"memory candidate not found: {candidate_id}"}, status=HTTPStatus.NOT_FOUND)
                return

            try:
                result = _apply_learning_memory_action(MemoryEngine(store), candidate_id, action)
            except ValueError as exc:
                message = str(exc)
                status = HTTPStatus.NOT_FOUND if "not found" in message else HTTPStatus.BAD_REQUEST
                self._send_json({"error": message}, status=status)
                return

            updated = store.get_memory_candidate(candidate_id) or candidate
            if candidate.get("run_id"):
                store.append_event(
                    candidate["run_id"],
                    "learning.memory_action",
                    {
                        "candidate_id": candidate_id,
                        "action": action,
                        "status": updated.get("status"),
                        "page_id": result.get("page_id"),
                        "source": "web",
                    },
                )
            self._send_json(
                {
                    "action": action,
                    "candidate": _learning_candidate_payload(updated),
                    "page_id": result.get("page_id"),
                }
            )

        def _handle_core_api(self, path: str) -> None:
            raw_method = path.removeprefix("/api/core/").strip("/")
            method = _core_method_name(raw_method)
            if not method:
                self._send_json({"error": f"unknown core API method: {raw_method}"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                body = self._read_json_body()
                result = _dispatch_core_api(config, method, body)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            except MnemoError as exc:
                status = HTTPStatus.NOT_FOUND if "not found" in str(exc).casefold() else HTTPStatus.BAD_REQUEST
                self._send_json({"error": str(exc)}, status=status)
                return
            self._send_json({"method": method, "result": result})

        def _send_asset(self, name: str, content_type: str) -> None:
            try:
                content = resources.files("mnemo.interfaces").joinpath("web_assets", name).read_bytes()
            except FileNotFoundError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("request body is required")
            raw_body = self.rfile.read(length)
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("request body must be JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _send_json(
            self,
            payload: dict[str, Any],
            status: HTTPStatus = HTTPStatus.OK,
            headers: dict[str, str] | None = None,
        ) -> None:
            body = dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _write_ndjson(self, payload: dict[str, Any]) -> None:
            self.wfile.write((dumps(payload) + "\n").encode("utf-8"))
            self.wfile.flush()

        def log_message(self, format: str, *args: Any) -> None:
            return None

    return Handler


def _stream_events(config: WebServerConfig, request: RunRequest):
    config = _effective_web_config(config)
    if config.provider == "local":
        yield from stream_local(request)
        return
    if config.provider == "openai-compatible":
        if not config.base_url or not config.model:
            raise ValueError("openai-compatible provider requires base_url and model")
        provider = OpenAIProviderAdapter(
            ProviderConfig(
                base_url=config.base_url,
                model=config.model,
                api_key=config.api_key,
                timeout_s=config.timeout_s,
                retry_count=config.retry_count,
                retry_backoff_s=config.retry_backoff_s,
                stream=True,
            )
        )
        yield from stream_provider(request, provider, max_tool_rounds=config.max_tool_rounds)
        return
    if config.provider == "anthropic":
        if not config.model:
            raise ValueError("anthropic provider requires model")
        provider = AnthropicProviderAdapter(
            ProviderConfig(
                base_url=config.base_url or _ANTHROPIC_DEFAULT_BASE_URL,
                model=config.model,
                api_key=config.api_key,
                timeout_s=config.timeout_s,
                retry_count=config.retry_count,
                retry_backoff_s=config.retry_backoff_s,
                stream=True,
            )
        )
        yield from stream_provider(request, provider, max_tool_rounds=config.max_tool_rounds)
        return
    raise ValueError(f"unsupported provider: {config.provider}")


class _AutoDreamScheduler:
    def __init__(
        self,
        config: WebServerConfig,
        *,
        interval_s: float = _AUTO_DREAM_TICK_INTERVAL_SECONDS,
        limit: int = 5,
    ) -> None:
        self.config = config
        self.interval_s = max(1.0, float(interval_s))
        self.limit = max(1, int(limit))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="mnemo-auto-dream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def tick_once(self, *, now: float | str | None = None) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            return {"processed": [], "skipped": "busy"}
        try:
            ensured = ensure_default_dream_schedule(self.config.state_dir, now=now)
            dream_runner = _dream_runner_for_web_config(self.config)
            if dream_runner is None:
                return {"processed": [], "auto_dream": ensured, "skipped": "provider_required"}
            result = ScheduleService(self.config.state_dir).tick(
                now=now,
                limit=self.limit,
                kind="dream",
                dream_runner=dream_runner,
            )
            result["auto_dream"] = ensured
            return result
        finally:
            self._lock.release()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick_once()
            except Exception as exc:
                print(f"Mnemo auto Dream scheduler error: {exc}")
            if self._stop.wait(self.interval_s):
                break


class _ProactiveScheduler:
    def __init__(
        self,
        config: WebServerConfig,
        *,
        interval_s: float = 60.0,
        schedule_limit: int = 20,
        drain_limit: int = 3,
    ) -> None:
        self.config = config
        self.interval_s = max(1.0, float(interval_s))
        self.schedule_limit = max(1, int(schedule_limit))
        self.drain_limit = max(1, int(drain_limit))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="mnemo-proactive", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def tick_once(self, *, now: float | str | None = None) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            return {"kind": "proactive_tick", "skipped": "busy"}
        try:
            service = ProactiveService(
                self.config.state_dir,
                workspace_root=self.config.workspace_root,
                executor=_run_executor_for_web_config(self.config),
            )
            return service.tick(now=now, schedule_limit=self.schedule_limit, drain_limit=self.drain_limit)
        finally:
            self._lock.release()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick_once()
            except Exception as exc:
                print(f"Mnemo proactive scheduler error: {exc}")
            if self._stop.wait(self.interval_s):
                break


def _run_executor_for_web_config(config: WebServerConfig) -> Callable[[RunRequest], Any]:
    def execute(request: RunRequest) -> Any:
        effective = _effective_web_config(config)
        if effective.provider == "local":
            return run_local(request)
        if effective.provider == "openai-compatible":
            if not effective.base_url or not effective.model:
                raise ValueError("openai-compatible provider requires base_url and model")
            provider = OpenAIProviderAdapter(
                ProviderConfig(
                    base_url=effective.base_url,
                    model=effective.model,
                    api_key=effective.api_key,
                    timeout_s=effective.timeout_s,
                    retry_count=effective.retry_count,
                    retry_backoff_s=effective.retry_backoff_s,
                    stream=False,
                )
            )
            return run_provider(request, provider, max_tool_rounds=effective.max_tool_rounds)
        if effective.provider == "anthropic":
            if not effective.model:
                raise ValueError("anthropic provider requires model")
            provider = AnthropicProviderAdapter(
                ProviderConfig(
                    base_url=effective.base_url or _ANTHROPIC_DEFAULT_BASE_URL,
                    model=effective.model,
                    api_key=effective.api_key,
                    timeout_s=effective.timeout_s,
                    retry_count=effective.retry_count,
                    retry_backoff_s=effective.retry_backoff_s,
                    stream=False,
                )
            )
            return run_provider(request, provider, max_tool_rounds=effective.max_tool_rounds)
        raise ValueError(f"unsupported provider: {effective.provider}")

    return execute


def _dream_runner_for_web_config(config: WebServerConfig) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    effective = _effective_web_config(config)
    if effective.provider == "local":
        return None
    if effective.provider == "openai-compatible":
        if not effective.base_url or not effective.model:
            return _failing_dream_runner("openai-compatible provider requires base_url and model")
        provider = OpenAIProviderAdapter(
            ProviderConfig(
                base_url=effective.base_url,
                model=effective.model,
                api_key=effective.api_key,
                timeout_s=effective.timeout_s,
                retry_count=effective.retry_count,
                retry_backoff_s=effective.retry_backoff_s,
                stream=True,
            )
        )
    elif effective.provider == "anthropic":
        if not effective.model:
            return _failing_dream_runner("anthropic provider requires model")
        provider = AnthropicProviderAdapter(
            ProviderConfig(
                base_url=effective.base_url or _ANTHROPIC_DEFAULT_BASE_URL,
                model=effective.model,
                api_key=effective.api_key,
                timeout_s=effective.timeout_s,
                retry_count=effective.retry_count,
                retry_backoff_s=effective.retry_backoff_s,
                stream=True,
            )
        )
    else:
        return _failing_dream_runner(f"unsupported provider: {effective.provider}")

    def run(item: dict[str, Any]) -> dict[str, Any]:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        dream_config = metadata.get("dream") if isinstance(metadata.get("dream"), dict) else {}
        return run_dream_with_provider(
            state_dir=effective.state_dir,
            provider=provider,
            workspace_root=effective.workspace_root,
            limit=int(dream_config.get("limit") or DEFAULT_DREAM_LIMIT),
            max_tool_rounds=effective.max_tool_rounds,
        )

    return run


def _failing_dream_runner(message: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def run(_item: dict[str, Any]) -> dict[str, Any]:
        raise ValueError(message)

    return run


def _effective_web_config(config: WebServerConfig) -> WebServerConfig:
    settings = load_user_settings(config.state_dir)
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    raw_runtime = _raw_runtime_settings(config.state_dir)
    api_key = config.api_key
    api_key_env = str(raw_runtime.get("api_key_env") or config.api_key_env or "").strip()
    if api_key_env:
        api_key = os.environ.get(api_key_env) or None
    timeout_s = runtime.get("timeout_s") if "timeout_s" in raw_runtime else config.timeout_s
    retry_count = runtime.get("retry_count") if "retry_count" in raw_runtime else config.retry_count
    retry_backoff_s = runtime.get("retry_backoff_s") if "retry_backoff_s" in raw_runtime else config.retry_backoff_s
    max_tool_rounds = runtime.get("max_tool_rounds") if "max_tool_rounds" in raw_runtime else config.max_tool_rounds
    return WebServerConfig(
        state_dir=config.state_dir,
        host=config.host,
        port=config.port,
        workspace_root=config.workspace_root,
        provider=str(runtime.get("provider") or config.provider or "local"),
        base_url=str(runtime.get("base_url") or config.base_url or "") or None,
        model=str(runtime.get("model") or config.model or "") or None,
        api_key=api_key,
        api_key_env=api_key_env or None,
        timeout_s=float(timeout_s if timeout_s is not None else config.timeout_s),
        retry_count=int(retry_count if retry_count is not None else config.retry_count),
        retry_backoff_s=float(retry_backoff_s if retry_backoff_s is not None else config.retry_backoff_s),
        max_tool_rounds=int(max_tool_rounds if max_tool_rounds is not None else config.max_tool_rounds),
    )


def _raw_runtime_settings(state_dir: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(settings_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    runtime = raw.get("runtime") if isinstance(raw, dict) else None
    return runtime if isinstance(runtime, dict) else {}


def _web_auth_config() -> WebAuthConfig:
    password = os.environ.get(_AUTH_PASSWORD_ENV) or ""
    password_hash = os.environ.get(_AUTH_PASSWORD_HASH_ENV) or ""
    if password:
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    password_hash = password_hash.strip().lower()
    if not password_hash:
        return WebAuthConfig(enabled=False)
    if len(password_hash) != 64 or any(char not in "0123456789abcdef" for char in password_hash):
        raise MnemoError(f"{_AUTH_PASSWORD_HASH_ENV} must be a 64-character SHA-256 hex digest")
    session_key = hashlib.sha256(f"mnemo-web-session:{password_hash}".encode("utf-8")).digest()
    return WebAuthConfig(enabled=True, password_hash=password_hash, session_key=session_key)


def _web_password_matches(auth: WebAuthConfig, password: str) -> bool:
    candidate = hashlib.sha256(str(password or "").encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, auth.password_hash)


def _auth_cookie_header(auth: WebAuthConfig) -> str:
    issued_at = str(int(time.time()))
    signature = hmac.new(auth.session_key, issued_at.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{issued_at}:{signature}".encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{_AUTH_COOKIE_NAME}={token}; Path=/; Max-Age={_AUTH_MAX_AGE_SECONDS}; HttpOnly; SameSite=Lax"


def _auth_cookie_is_valid(auth: WebAuthConfig, cookie_header: str) -> bool:
    if not cookie_header:
        return False
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return False
    morsel = cookie.get(_AUTH_COOKIE_NAME)
    if morsel is None:
        return False
    token = morsel.value
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8")
        issued_text, signature = raw.split(":", 1)
        issued_at = int(issued_text)
    except Exception:
        return False
    now = int(time.time())
    if issued_at > now + 60 or now - issued_at > _AUTH_MAX_AGE_SECONDS:
        return False
    expected = hmac.new(auth.session_key, issued_text.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _login_page_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Mnemo 登录</title>
    <style>
      :root { color-scheme: light; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f6f7f9; color: #17191f; }
      main { width: min(360px, calc(100vw - 40px)); }
      h1 { margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }
      p { margin: 0 0 24px; color: #5c6370; line-height: 1.6; }
      form { display: grid; gap: 12px; }
      label { display: grid; gap: 8px; font-size: 13px; color: #4a5160; }
      input { width: 100%; box-sizing: border-box; border: 1px solid #cdd3dc; border-radius: 8px; padding: 12px 14px; font: inherit; background: #fff; }
      button { border: 0; border-radius: 8px; padding: 12px 14px; font: inherit; font-weight: 650; background: #17191f; color: #fff; cursor: pointer; }
      button:disabled { cursor: progress; opacity: 0.7; }
      .error { min-height: 20px; color: #b42318; font-size: 13px; }
    </style>
  </head>
  <body>
    <main>
      <h1>Mnemo</h1>
      <p>请输入访问密码。</p>
      <form id="loginForm">
        <label>
          密码
          <input id="password" name="password" type="password" autocomplete="current-password" autofocus />
        </label>
        <button id="submit" type="submit">进入</button>
        <div id="error" class="error" role="status"></div>
      </form>
    </main>
    <script>
      const form = document.querySelector("#loginForm");
      const input = document.querySelector("#password");
      const submit = document.querySelector("#submit");
      const error = document.querySelector("#error");
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        error.textContent = "";
        submit.disabled = true;
        try {
          const response = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: input.value }),
          });
          if (!response.ok) {
            error.textContent = "密码不正确";
            return;
          }
          window.location.href = "/";
        } catch (_error) {
          error.textContent = "无法连接 Mnemo";
        } finally {
          submit.disabled = false;
        }
      });
    </script>
  </body>
</html>"""


def _dispatch_core_api(config: WebServerConfig, method: str, body: dict[str, Any]) -> dict[str, Any]:
    client = MnemoClient(state_dir=config.state_dir, workspace_root=config.workspace_root)
    if method == "context":
        return client.context(
            _string_field(body, "intent", default=""),
            agent_role=_string_field(body, "agent_role", default="general"),
            budget_tokens=_int_field(body, "budget_tokens", default=4000),
            include_associations=_bool_field(body, "include_associations", default=True),
            prompt_mode=_string_field(body, "prompt_mode", default="full"),
        )
    if method == "recall":
        return client.recall(
            _required_string(body, "seed"),
            depth=_int_field(body, "depth", default=2),
            context=_string_field(body, "context", default=""),
            limit=_int_field(body, "limit", default=8),
        )
    if method == "capsule":
        return client.capsule(
            _required_string(body, "task"),
            runtime=_string_field(body, "runtime", default="external"),
            agent_type=_string_field(body, "agent_type", default="general"),
            requested_pages=_string_list_field(body, "requested_pages"),
            allowed_pages=_string_list_field(body, "allowed_pages"),
            conversation_id=_optional_string(body.get("conversation_id")),
            mission_id=_optional_string(body.get("mission_id")),
            limit=_int_field(body, "limit", default=8),
        )
    if method == "external_run":
        return client.external_run(
            _required_string(body, "task"),
            command=_required_string_list_field(body, "command"),
            runtime=_string_field(body, "runtime", default="external-command"),
            agent_type=_string_field(body, "agent_type", default="general"),
            requested_pages=_string_list_field(body, "requested_pages"),
            allowed_pages=_string_list_field(body, "allowed_pages"),
            conversation_id=_optional_string(body.get("conversation_id")),
            mission_id=_optional_string(body.get("mission_id")),
            timeout_s=_float_field(body, "timeout_s", default=30.0),
        )
    if method == "run":
        return client.run(
            _required_string(body, "message"),
            conversation_id=_optional_string(body.get("conversation_id")),
            mission_id=_optional_string(body.get("mission_id")),
            prompt_mode=_string_field(body, "prompt_mode", default="full"),
        )
    if method == "schedule_dream":
        return client.schedule_dream(
            schedule=_string_field(body, "schedule", default="daily"),
            title=_optional_string(body.get("title")),
            next_run_at=_optional_schedule_time(body, "next_run_at"),
            limit=_int_field(body, "limit", default=20),
            min_confidence=_float_field(body, "min_confidence", default=0.7),
            source=_string_field(body, "source", default="http"),
        )
    if method == "schedule_watch":
        target = _required_string(body, "target")
        return client.schedule_watch(
            target,
            instruction=_string_field(body, "instruction", default=target),
            schedule=_string_field(body, "schedule", default="daily"),
            next_run_at=_optional_schedule_time(body, "next_run_at"),
            source=_string_field(body, "source", default="http"),
        )
    if method == "schedule_cron":
        return client.schedule_cron(
            _required_string(body, "message"),
            schedule=_string_field(body, "schedule", default="once"),
            title=_optional_string(body.get("title")),
            next_run_at=_optional_schedule_time(body, "next_run_at"),
            source=_string_field(body, "source", default="http"),
        )
    if method == "runtime_status":
        return client.runtime_status(limit=_int_field(body, "limit", default=10))
    if method == "replay":
        return client.replay(_required_string(body, "run_id"))
    if method == "evaluate":
        return client.evaluate(
            _string_field(body, "suite", default="smoke"),
            variants=_string_list_field(body, "variants") or None,
            release_gate=_bool_field(body, "release_gate", default=False),
        )
    raise ValueError(f"unsupported core API method: {method}")


def _core_method_name(value: str) -> str | None:
    method = value.replace("-", "_")
    if method in mnemo_core_api_schema()["methods"]:
        return method
    return None


def _core_openapi_schema() -> dict[str, Any]:
    core_schema = mnemo_core_api_schema()
    paths: dict[str, Any] = {
        "/api/core/schema": {
            "get": {
                "operationId": "schema",
                "summary": "Return the MnemoCore API schema.",
                "responses": {"200": {"description": "MnemoCore API schema"}},
            }
        },
        "/api/core/openapi.json": {
            "get": {
                "operationId": "openapi",
                "summary": "Return this compact OpenAPI document.",
                "responses": {"200": {"description": "OpenAPI document"}},
            }
        },
    }
    for name, method in core_schema["methods"].items():
        path_name = name.replace("_", "-")
        paths[f"/api/core/{path_name}"] = {
            "post": {
                "operationId": name,
                "summary": method["description"],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": method["input_schema"]}},
                },
                "responses": {
                    "200": {
                        "description": "Core API result",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "method": {"const": name},
                                        "result": method["output_schema"],
                                    },
                                    "required": ["method", "result"],
                                }
                            }
                        },
                    },
                    "400": {"description": "Invalid request"},
                    "404": {"description": "Unknown method or missing resource"},
                },
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": core_schema["title"],
            "version": core_schema["schema_version"],
            "description": core_schema["description"],
        },
        "paths": paths,
    }


def _settings_payload(config: WebServerConfig) -> dict[str, Any]:
    store = StateStore(config.state_dir)
    store.initialize()
    open_decisions = store.list_inbox_items(status="open", category="decision", limit=100)
    memory_pages = store.list_memory_pages(status="active", limit=1000)
    memory_candidates = store.list_memory_candidates(status=None, limit=1000)
    artifacts = store.list_artifacts(limit=1000)
    scheduled = store.list_scheduled_items(status="active", limit=100)
    preferences = _preference_cards(memory_pages)
    settings = load_user_settings(config.state_dir)
    effective = _effective_web_config(config)
    feishu_status = feishu_channel_status(config.state_dir)

    return {
        "settings": settings,
        "runtime": {
            "provider": effective.provider,
            "model": effective.model or "",
            "base_url": effective.base_url or "",
            "api_key_env": effective.api_key_env or "",
            "timeout_s": effective.timeout_s,
            "retry_count": effective.retry_count,
            "retry_backoff_s": effective.retry_backoff_s,
            "max_tool_rounds": effective.max_tool_rounds,
            "current": {
                "provider": config.provider,
                "model": config.model or "",
                "base_url": config.base_url or "",
                "timeout_s": config.timeout_s,
                "retry_count": config.retry_count,
                "retry_backoff_s": config.retry_backoff_s,
                "max_tool_rounds": config.max_tool_rounds,
            },
            "applies": "live",
        },
        "connected_apps": [*_connected_app_cards(effective), _feishu_connected_app_card(feishu_status)],
        "channels": {
            "feishu": feishu_status,
        },
        "proactive": proactive_status(config.state_dir),
        "permissions": {
            "open_decisions": len(open_decisions),
            "risk_policy": [
                {"risk": "read", "behavior": "run"},
                {"risk": "write", "behavior": "run_in_trusted_workspace"},
                {"risk": "external", "behavior": "decision_card"},
                {"risk": "admin", "behavior": "explicit_confirmation"},
            ],
        },
        "quiet_hours": settings["quiet_hours"],
        "learned_preferences": {
            "count": len(preferences),
            "items": preferences[:8],
            "review_prompt": "Review my learned preferences.",
        },
        "data_controls": {
            "counts": {
                "memory_pages": len(memory_pages),
                "memory_candidates": len(memory_candidates),
                "artifacts": len(artifacts),
                "open_decisions": len(open_decisions),
                "scheduled_items": len(scheduled),
            },
            "actions": [
                {"id": "review_preferences", "label": "Review preferences", "prompt": "Review my learned preferences."},
                {"id": "forget", "label": "Forget something", "prompt": "Forget: "},
                {"id": "export", "label": "Export data", "prompt": "Export my Mnemo data."},
            ],
        },
    }

def _catalog_payload(config: WebServerConfig) -> dict[str, Any]:
    store = StateStore(config.state_dir)
    store.initialize()
    skill_service = SkillService(
        store,
        roots=default_skill_roots(config.state_dir, workspace=config.workspace_root),
    )
    skill_service.scan()
    skills = skill_service.context_cards(limit=1000)

    registry = ToolRegistry.from_store(store)
    active_generated_tools = {
        str(tool.get("name"))
        for tool in store.list_generated_tools(status="active", limit=1000)
        if tool.get("name")
    }
    bundle = registry.tool_bundle().metadata()
    bundled_names = set(bundle.get("tool_names", []))
    tools = [
        _tool_catalog_card(spec, generated=spec.name in active_generated_tools, in_bundle=spec.name in bundled_names)
        for spec in sorted(registry.specs(), key=lambda item: item.name)
    ]
    return {
        "kind": "capability_catalog",
        "version": "mnemo.catalog.v1",
        "skills": skills,
        "tools": tools,
        "tool_bundle": bundle,
        "counts": {
            "skills": {
                "total": len(skills),
                "status": _count_by(skills, "status"),
            },
            "tools": {
                "total": len(tools),
                "risk": _count_by(tools, "risk"),
                "generated": sum(1 for tool in tools if tool.get("source") == "generated"),
                "in_bundle": sum(1 for tool in tools if tool.get("in_bundle")),
            },
        },
    }


def _tool_catalog_card(spec: Any, *, generated: bool, in_bundle: bool) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "risk": spec.risk,
        "source": "generated" if generated else "built-in",
        "in_bundle": in_bundle,
    }


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _memory_ontology_payload(config: WebServerConfig) -> dict[str, Any]:
    store = StateStore(config.state_dir)
    store.initialize()
    pages = _dedupe_memory_pages(store.list_memory_pages(status="active", limit=1000))
    candidates = _dedupe_memory_candidates([
        candidate
        for candidate in store.list_memory_candidates(status=None, limit=1000)
        if _is_open_memory_candidate(candidate)
    ])
    buckets = {
        dimension: {
            "dimension": dimension,
            "level": "L1",
            "pages": 0,
            "candidates": 0,
            "summary": "",
            "next_level": "dimension",
            "dimension_url": f"/api/memory/dimension?dimension={dimension}",
            "_samples": [],
        }
        for dimension in MEMORY_ONTOLOGY_DIMENSIONS
    }
    for page in pages:
        dimension = _memory_dimension(page, fallback="context")
        bucket = buckets[dimension]
        bucket["pages"] += 1
        if len(bucket["_samples"]) < 2:
            bucket["_samples"].append(_memory_display_title(str(page.get("title") or dimension)))
    for candidate in candidates:
        dimension = _memory_dimension(candidate, fallback="context")
        bucket = buckets[dimension]
        bucket["candidates"] += 1
        if len(bucket["_samples"]) < 2:
            bucket["_samples"].append(_memory_display_title(str(candidate.get("claim") or dimension)))
    dimensions = []
    for dimension in MEMORY_ONTOLOGY_DIMENSIONS:
        item = dict(buckets[dimension])
        samples = item.pop("_samples", [])
        item["summary"] = _memory_dimension_summary(dimension, samples, item["pages"], item["candidates"])
        dimensions.append(item)
    return {
        "kind": "memory_ontology",
        "level": "L1",
        "dimensions": dimensions,
        "counts": {
            "pages": len(pages),
            "candidates": len(candidates),
            "covered_dimensions": sum(
                1 for item in dimensions if int(item["pages"]) + int(item["candidates"]) > 0
            ),
        },
    }


def _memory_dimension_payload(config: WebServerConfig, dimension: str) -> dict[str, Any]:
    store = StateStore(config.state_dir)
    store.initialize()
    pages = [
        page
        for page in _dedupe_memory_pages(store.list_memory_pages(status="active", limit=1000))
        if _memory_dimension(page, fallback="context") == dimension
    ]
    candidates = [
        candidate
        for candidate in _dedupe_memory_candidates(
            [
                candidate
                for candidate in store.list_memory_candidates(status=None, limit=1000)
                if _is_open_memory_candidate(candidate)
            ]
        )
        if _memory_dimension(candidate, fallback="context") == dimension
    ]
    page_items = [_memory_l2_page_card(page) for page in pages]
    candidate_items = [_memory_l2_candidate_card(candidate) for candidate in candidates]
    return {
        "kind": "memory_dimension",
        "level": "L2",
        "dimension": dimension,
        "summary": _memory_dimension_summary(
            dimension,
            [item["title"] for item in [*page_items, *candidate_items]][:2],
            len(page_items),
            len(candidate_items),
        ),
        "counts": {
            "pages": len(page_items),
            "candidates": len(candidate_items),
        },
        "pages": page_items,
        "candidates": candidate_items,
    }


def _memory_item_payload(config: WebServerConfig, item_type: str, item_id: str) -> dict[str, Any] | None:
    store = StateStore(config.state_dir)
    store.initialize()
    normalized_type = str(item_type or "").strip().lower()
    if normalized_type in {"page", "memory_page", "stable"}:
        page = store.get_memory_page(item_id)
        if not page:
            return None
        if str(page.get("status") or "") != "active":
            return None
        dimension = _memory_dimension(page, fallback="context")
        source_candidate = (
            store.get_memory_candidate(str(page.get("source_candidate_id")))
            if page.get("source_candidate_id")
            else None
        )
        tombstones = store.list_memory_tombstones(target_id=item_id, target_type="page", limit=5)
        detail = _memory_l3_page_detail(page, dimension)
        evidence = _memory_item_evidence(source_candidate, tombstones)
        wiki = _memory_page_wiki_note(config, page)
        detail = dict(detail)
        detail["title"] = wiki["title"]
        return {
            "kind": "memory_item",
            "level": "L3",
            "item": detail,
            "evidence": evidence,
            "markdown": wiki["markdown"],
        }
    if normalized_type in {"candidate", "memory_candidate"}:
        candidate = store.get_memory_candidate(item_id)
        if not candidate:
            return None
        if not _is_open_memory_candidate(candidate):
            return None
        dimension = _memory_dimension(candidate, fallback="context")
        tombstones = store.list_memory_tombstones(target_id=item_id, target_type="candidate", limit=5)
        detail = _memory_l3_candidate_detail(candidate, dimension)
        evidence = _memory_item_evidence(candidate, tombstones, include_source_candidate=False)
        wiki = _memory_candidate_wiki_note(config, detail, evidence)
        detail = dict(detail)
        detail["title"] = wiki["title"]
        return {
            "kind": "memory_item",
            "level": "L3",
            "item": detail,
            "evidence": evidence,
            "markdown": wiki["markdown"],
        }
    raise ValueError(f"unsupported memory item type: {item_type}")


def _memory_dimension(item: dict[str, Any], *, fallback: str) -> str:
    value = str(item.get("dimension") or "")
    if not value:
        title = str(item.get("title") or "").strip()
        value = title.split(":", 1)[0] if ":" in title else ""
    return normalize_memory_dimension(value, fallback=fallback)


def _is_open_memory_candidate(candidate: dict[str, Any]) -> bool:
    status = str(candidate.get("status") or "")
    return status == "draft" or status.startswith("needs_review")


def _memory_l2_page_card(page: dict[str, Any]) -> dict[str, Any]:
    dimension = _memory_dimension(page, fallback="context")
    summary = str(page.get("content") or "")
    return {
        "kind": "page",
        "id": page.get("id"),
        "title": _clip_text(
            _memory_display_title(str(page.get("title") or "")) or _MEMORY_DIMENSION_LABELS.get(dimension, dimension),
            90,
        ),
        "summary": _clip_text(summary, 180),
        "confidence": page.get("confidence"),
        "status": page.get("status"),
        "updated_at": page.get("updated_at"),
        "detail_url": f"/api/memory/item?type=page&id={page.get('id')}",
    }


def _memory_l2_candidate_card(candidate: dict[str, Any]) -> dict[str, Any]:
    dimension = _memory_dimension(candidate, fallback="context")
    claim = str(candidate.get("claim") or "")
    return {
        "kind": "candidate",
        "id": candidate.get("id"),
        "title": _clip_text(
            _memory_display_title(claim) or f"{_MEMORY_DIMENSION_LABELS.get(dimension, dimension)}候选",
            90,
        ),
        "summary": _clip_text(str(candidate.get("status") or "candidate"), 120),
        "confidence": candidate.get("confidence"),
        "status": candidate.get("status"),
        "created_at": candidate.get("created_at"),
        "detail_url": f"/api/memory/item?type=candidate&id={candidate.get('id')}",
    }


def _memory_l3_page_detail(page: dict[str, Any], dimension: str) -> dict[str, Any]:
    summary = str(page.get("content") or "")
    return {
        "type": "page",
        "id": page.get("id"),
        "dimension": dimension,
        "title": _clip_text(
            _memory_display_title(str(page.get("title") or "")) or _MEMORY_DIMENSION_LABELS.get(dimension, dimension),
            120,
        ),
        "summary": _clip_text(summary, 700),
        "scope": page.get("scope"),
        "confidence": page.get("confidence"),
        "status": page.get("status"),
        "source_candidate_id": page.get("source_candidate_id"),
        "created_at": page.get("created_at"),
        "updated_at": page.get("updated_at"),
    }


def _memory_l3_candidate_detail(candidate: dict[str, Any], dimension: str) -> dict[str, Any]:
    claim = str(candidate.get("claim") or "")
    return {
        "type": "candidate",
        "id": candidate.get("id"),
        "dimension": dimension,
        "title": _clip_text(
            _memory_display_title(claim) or f"{_MEMORY_DIMENSION_LABELS.get(dimension, dimension)}候选",
            120,
        ),
        "summary": _clip_text(claim, 700),
        "scope": candidate.get("scope"),
        "confidence": candidate.get("confidence"),
        "status": candidate.get("status"),
        "created_at": candidate.get("created_at"),
    }


def _memory_item_evidence(
    source_candidate: dict[str, Any] | None,
    tombstones: list[dict[str, Any]],
    *,
    include_source_candidate: bool = True,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    if source_candidate and include_source_candidate:
        evidence.append(
            {
                "kind": "source_candidate",
                "id": source_candidate.get("id"),
                "summary": _clip_text(str(source_candidate.get("claim") or ""), 180),
                "status": source_candidate.get("status"),
                "confidence": source_candidate.get("confidence"),
                "run_id": source_candidate.get("run_id"),
            }
        )
    if source_candidate:
        for item in source_candidate.get("evidence", [])[:3]:
            if not isinstance(item, dict):
                continue
            evidence.append(
                {
                    "kind": str(item.get("kind") or "evidence"),
                    "summary": _clip_text(
                        str(item.get("summary") or item.get("text") or item.get("source") or item.get("id") or ""),
                        180,
                    ),
                }
            )
    for tombstone in tombstones[:3]:
        evidence.append(
            {
                "kind": "tombstone",
                "id": tombstone.get("id"),
                "summary": _clip_text(str(tombstone.get("summary") or tombstone.get("reason") or ""), 180),
                "reason": tombstone.get("reason"),
                "created_at": tombstone.get("created_at"),
            }
        )
    return evidence


def _memory_page_wiki_note(config: WebServerConfig, page: dict[str, Any]) -> dict[str, str]:
    path = memory_page_wiki_path(config.state_dir, page)
    if not path.exists():
        materialize_memory_page(config.state_dir, page)
    markdown = path.read_text(encoding="utf-8")
    title = _markdown_h1(markdown) or _memory_display_title(str(page.get("title") or "")) or "Memory"
    return {
        "title": _clip_text(title, 120),
        "markdown": markdown,
    }


def _memory_candidate_wiki_note(
    config: WebServerConfig,
    detail: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, str]:
    title = _memory_wiki_clean_title(str(detail.get("title") or ""), detail)
    body = str(detail.get("summary") or "").strip() or "_暂无正文。_"
    return {
        "title": title,
        "markdown": _memory_item_markdown(config.state_dir, detail, evidence, title=title, body_markdown=body),
    }


def _markdown_h1(markdown: str) -> str:
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _memory_item_markdown(
    state_dir: str,
    detail: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    title: str,
    body_markdown: str,
) -> str:
    dimension = normalize_memory_dimension(str(detail.get("dimension") or ""), fallback="context")
    kind = str(detail.get("type") or "memory").strip() or "memory"
    frontmatter = {
        "kind": kind,
        "id": str(detail.get("id") or ""),
        "dimension": dimension,
        "status": str(detail.get("status") or "unknown"),
        "confidence": _memory_wiki_confidence(detail.get("confidence")),
        "scope": str(detail.get("scope") or "global"),
        "wiki_path": _memory_item_wiki_path(state_dir, detail, dimension, title=title),
        "updated_at": _memory_wiki_timestamp(detail.get("updated_at") or detail.get("created_at")),
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        if value:
            lines.append(f"{key}: {value}")
    lines.extend(["---", "", f"# {title}", "", "## 概述", ""])
    if body_markdown.strip():
        lines.append(body_markdown.strip())
    else:
        lines.append("_暂无正文。_")
    if evidence:
        lines.extend(["", "## 证据", ""])
        for item in evidence:
            prefix = _memory_wiki_evidence_label(str(item.get("kind") or "evidence"))
            summary = str(item.get("summary") or item.get("reason") or "").strip()
            if summary:
                lines.append(f"- {prefix}: {summary}")
    return "\n".join(lines)


def _memory_wiki_clean_title(title: str, detail: dict[str, Any]) -> str:
    compact = " ".join(str(title or "").strip().split())
    compact = compact.lstrip("#").strip()
    if compact:
        return _clip_text(compact, 40)
    dimension = normalize_memory_dimension(str(detail.get("dimension") or ""), fallback="context")
    if detail.get("type") == "candidate":
        return f"{_MEMORY_DIMENSION_LABELS.get(dimension, dimension)}候选"
    return _MEMORY_DIMENSION_LABELS.get(dimension, dimension)


def _memory_item_wiki_path(state_dir: str, detail: dict[str, Any], dimension: str, *, title: str) -> str:
    item_id = str(detail.get("id") or "").strip()
    if not item_id or detail.get("type") != "page":
        return ""
    return memory_page_wiki_ref(
        state_dir,
        {
            "id": item_id,
            "title": title,
            "scope": detail.get("scope"),
            "status": detail.get("status"),
            "metadata": {"dimension": dimension},
        },
    ).removeprefix("./")


def _dedupe_memory_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _dedupe_memory_items(pages, value_getter=lambda page: str(page.get("content") or ""))


def _dedupe_memory_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _dedupe_memory_items(candidates, value_getter=lambda candidate: str(candidate.get("claim") or ""))


def _dedupe_memory_items(
    items: list[dict[str, Any]],
    *,
    value_getter: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    selected: dict[str, tuple[int, dict[str, Any]]] = {}
    passthrough: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(items):
        key = _memory_duplicate_key(value_getter(item))
        if not key:
            passthrough.append((index, item))
            continue
        existing = selected.get(key)
        if existing is None:
            selected[key] = (index, item)
            continue
        existing_index, existing_item = existing
        if _memory_dedupe_preference(item) < _memory_dedupe_preference(existing_item):
            selected[key] = (existing_index, item)
    ordered = [*passthrough, *selected.values()]
    ordered.sort(key=lambda pair: pair[0])
    return [item for _, item in ordered]


def _memory_duplicate_key(value: str) -> str:
    compact = "".join(char for char in str(value or "").casefold() if char.isalnum())
    return compact if len(compact) >= 12 else ""


def _memory_dedupe_preference(item: dict[str, Any]) -> tuple[int, float, str]:
    dimension = _memory_dimension(item, fallback="context")
    try:
        dimension_rank = MEMORY_ONTOLOGY_DIMENSIONS.index(dimension)
    except ValueError:
        dimension_rank = len(MEMORY_ONTOLOGY_DIMENSIONS)
    try:
        confidence = float(item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return (dimension_rank, -confidence, str(item.get("id") or ""))


def _memory_wiki_confidence(value: Any) -> str:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{confidence:.2f}".rstrip("0").rstrip(".")


def _memory_wiki_timestamp(value: Any) -> str:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()


def _memory_wiki_evidence_label(kind: str) -> str:
    normalized = "_".join(kind.strip().lower().replace("-", "_").split())
    return _MEMORY_EVIDENCE_LABELS.get(normalized, normalized or "证据")


def _memory_display_title(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if ":" not in text:
        return text
    head, body = text.split(":", 1)
    if is_known_memory_dimension(head):
        return body.strip() or head.strip()
    return text


def _memory_dimension_summary(dimension: str, samples: list[str], pages: int, candidates: int) -> str:
    if pages == 0 and candidates == 0:
        return "尚未沉淀稳定信号。"
    sample_text = "；".join(_clip_text(sample, 60) for sample in samples if sample)
    prefix = f"{pages} 条稳定记忆"
    if candidates:
        prefix += f" · {candidates} 条候选"
    return f"{prefix}。{sample_text}" if sample_text else f"{prefix}。"


def _clip_text(value: str, limit: int) -> str:
    compact = " ".join(value.strip().split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 14)].rstrip() + "...[truncated]"


def _connected_app_cards(config: WebServerConfig) -> list[dict[str, Any]]:
    provider_detail = config.provider
    if config.model:
        provider_detail = f"{config.provider} · {config.model}"
    return [
        {
            "id": "runtime",
            "label": "Runtime",
            "status": "local" if config.provider == "local" else "connected",
            "detail": provider_detail,
        },
        {
            "id": "workspace",
            "label": "Workspace",
            "status": "connected" if config.workspace_root else "not_connected",
            "detail": _path_label(config.workspace_root) if config.workspace_root else "none",
        },
        {
            "id": "mcp",
            "label": "MCP",
            "status": "available",
            "detail": "Content-Length stdio",
        },
    ]


def _feishu_connected_app_card(status: dict[str, Any]) -> dict[str, Any]:
    detail = "not configured"
    if status.get("configured"):
        label = status.get("bot_name") or status.get("bot_open_id") or status.get("app_id") or "configured"
        detail = f"{status.get('domain') or 'feishu'} · {label}"
    return {
        "id": "feishu",
        "label": "Feishu/Lark",
        "status": "connected" if status.get("configured") else "not_connected",
        "detail": detail,
    }


def _preference_cards(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for page in pages:
        haystack = f"{page.get('title') or ''} {page.get('content') or ''}".casefold()
        if "preference" not in haystack and "preferences" not in haystack:
            continue
        cards.append(
            {
                "id": page.get("id"),
                "title": page.get("title") or "Preference",
                "summary": _truncate(page.get("content"), limit=160),
                "confidence": page.get("confidence"),
                "updated_at": page.get("updated_at"),
            }
        )
    return cards


def _path_label(value: str | None) -> str:
    if not value:
        return "none"
    name = Path(value).expanduser().name
    return name or "workspace"


def _truncate(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _string_field(payload: dict[str, Any], key: str, *, default: str) -> str:
    if key not in payload or payload.get(key) is None:
        return default
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip()


def _int_field(payload: dict[str, Any], key: str, *, default: int) -> int:
    if key not in payload or payload.get(key) is None:
        return default
    value = payload.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _float_field(payload: dict[str, Any], key: str, *, default: float) -> float:
    if key not in payload or payload.get(key) is None:
        return default
    value = payload.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc


def _bool_field(payload: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in payload or payload.get(key) is None:
        return default
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _string_list_field(payload: dict[str, Any], key: str) -> list[str]:
    if key not in payload or payload.get(key) is None:
        return []
    return _required_string_list_field(payload, key)


def _required_string_list_field(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{key} must be an array of non-empty strings")
    return [item.strip() for item in value]


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_schedule_time(payload: dict[str, Any], key: str) -> float | str | None:
    if key not in payload or payload.get(key) is None:
        return None
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{key} must be a string, number, or null")
    if isinstance(value, str):
        return value.strip() or None
    return float(value)


def _first_param(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key) or []
    return values[0] if values else None


def _int_param(params: dict[str, list[str]], key: str, default: int) -> int:
    value = _first_param(params, key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _bool_param(params: dict[str, list[str]], key: str, default: bool) -> bool:
    value = _first_param(params, key)
    if value is None:
        return default
    return value.casefold() in {"1", "true", "yes", "on"}


def _priority_lte(priority: str | None) -> int | None:
    if priority is None:
        return None
    priorities = {
        "critical": 0,
        "high": 1,
        "normal": 2,
        "low": 3,
    }
    value = priorities.get(priority.casefold())
    if value is None:
        raise ValueError(f"invalid priority: {priority}")
    return value


def _learning_action(action: str) -> str:
    normalized = action.strip().casefold()
    if normalized not in {"accept", "this_time", "reject", "undo"}:
        raise ValueError(f"invalid learning action: {action}")
    return normalized


def _apply_learning_memory_action(engine: MemoryEngine, candidate_id: str, action: str) -> dict[str, Any]:
    if action == "accept":
        return engine.promote_candidate(candidate_id)
    if action == "this_time":
        return engine.reject_candidate(candidate_id, "this time only")
    if action == "reject":
        return engine.reject_candidate(candidate_id, "user rejected")
    if action == "undo":
        return engine.undo_candidate(candidate_id)
    raise ValueError(f"invalid learning action: {action}")


def _learning_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate["id"],
        "run_id": candidate.get("run_id"),
        "dimension": candidate.get("dimension"),
        "scope": candidate.get("scope"),
        "confidence": candidate.get("confidence"),
        "status": candidate.get("status"),
        "created_at": candidate.get("created_at"),
    }


def _last_chat_event_id(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        event_id = event.get("event_id")
        if isinstance(event_id, str) and event_id:
            return event_id
    return None
