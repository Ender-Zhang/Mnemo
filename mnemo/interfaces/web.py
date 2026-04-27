from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
import json
from pathlib import Path
import socket
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..core.events import chat_event_as_dict
from ..core.errors import MnemoError
from ..core.jsonutil import dumps
from ..core.models import RunRequest
from ..core.settings import load_user_settings, save_user_settings
from ..providers import AnthropicProviderAdapter, OpenAIProviderAdapter, ProviderConfig
from ..runtime import stream_local, stream_provider
from ..runtime.approvals import resolve_inbox_item_with_actions
from ..runtime.ledger import RunLedger
from ..memory import MemoryEngine
from ..sdk import MnemoClient, mnemo_core_api_schema
from ..storage import StateStore


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
    timeout_s: float = 30.0
    retry_count: int = 0
    retry_backoff_s: float = 0.0


_ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


def build_http_server(config: WebServerConfig) -> ThreadingHTTPServer:
    StateStore(config.state_dir).initialize()
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
    server = build_http_server(config)
    host, port = server.server_address
    print(f"Mnemo web listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
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


def _handler_for(config: WebServerConfig) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MnemoWeb/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_asset("index.html", "text/html; charset=utf-8")
            elif parsed.path == "/app.css":
                self._send_asset("app.css", "text/css; charset=utf-8")
            elif parsed.path == "/app.js":
                self._send_asset("app.js", "application/javascript; charset=utf-8")
            elif parsed.path == "/api/health":
                self._send_json({"ok": True, "provider": config.provider})
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
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
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
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

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

            try:
                for event in _stream_events(config, request):
                    self._write_ndjson(chat_event_as_dict(event))
            except Exception as exc:
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

        def _handle_settings_update(self) -> None:
            try:
                body = self._read_json_body()
                save_user_settings(config.state_dir, body)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(_settings_payload(config))

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

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_ndjson(self, payload: dict[str, Any]) -> None:
            self.wfile.write((dumps(payload) + "\n").encode("utf-8"))
            self.wfile.flush()

        def log_message(self, format: str, *args: Any) -> None:
            return None

    return Handler


def _stream_events(config: WebServerConfig, request: RunRequest):
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
        yield from stream_provider(request, provider)
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
        yield from stream_provider(request, provider)
        return
    raise ValueError(f"unsupported provider: {config.provider}")


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

    return {
        "settings": settings,
        "connected_apps": _connected_app_cards(config),
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
