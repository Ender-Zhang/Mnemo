from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
import json
import socket
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..core.events import chat_event_as_dict
from ..core.jsonutil import dumps
from ..core.models import RunRequest
from ..providers import AnthropicProviderAdapter, OpenAIProviderAdapter, ProviderConfig
from ..runtime import stream_local, stream_provider
from ..runtime.ledger import RunLedger
from ..storage import StateStore


@dataclass(frozen=True)
class WebServerConfig:
    state_dir: str
    host: str = "127.0.0.1"
    port: int = 8765
    provider: str = "local"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float = 30.0


_ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


def build_http_server(config: WebServerConfig) -> HTTPServer:
    StateStore(config.state_dir).initialize()
    handler = _handler_for(config)
    return MnemoHTTPServer((config.host, config.port), handler)


class MnemoHTTPServer(HTTPServer):
    allow_reuse_address = True

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
            elif parsed.path == "/api/events":
                self._handle_events(parsed.query)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/chat":
                self._handle_chat()
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

        def _handle_events(self, query: str) -> None:
            params = parse_qs(query)
            run_id = _first_param(params, "run_id")
            if not run_id:
                self._send_json({"error": "run_id is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            since = _int_param(params, "since", 0)
            chat_only = _bool_param(params, "chat", True)
            store = StateStore(config.state_dir)
            store.initialize()
            ledger = RunLedger(store)
            events = ledger.chat_events(run_id, since=since) if chat_only else ledger.events_since(run_id, since=since)
            self._send_json({"events": events})

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
                stream=True,
            )
        )
        yield from stream_provider(request, provider)
        return
    raise ValueError(f"unsupported provider: {config.provider}")


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


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
