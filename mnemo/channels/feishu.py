from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from ..core.config import DEFAULT_MAX_TOOL_ROUNDS
from ..core.errors import MnemoError
from ..core.jsonutil import dumps
from ..core.models import RunRequest
from ..core.workspace import resolve_workspace_root
from ..providers import AnthropicProviderAdapter, OpenAIProviderAdapter, ProviderConfig
from ..runtime import run_local, run_provider
from ..storage import StateStore


_DEFAULT_WEBHOOK_PATH = "/feishu/webhook"
_DEFAULT_BODY_LIMIT_BYTES = 1_000_000
_DEDUP_TTL_SECONDS = 24 * 60 * 60
_FEISHU_API_BASE_URL = "https://open.feishu.cn"
_LARK_API_BASE_URL = "https://open.larksuite.com"
_TEXT_CHUNK_SIZE = 3900


@dataclass(frozen=True)
class FeishuChannelConfig:
    """Dependency-free Feishu/Lark webhook channel config.

    Acknowledgement: this transport borrows the boundary shape from
    NousResearch Hermes Agent's Feishu gateway implementation: URL
    verification before auth, verification-token and signature checks,
    callback deduplication, per-chat serialization, and background handling.
    The implementation here is Mnemo-specific and routes into Mnemo runtime
    services instead of copying Hermes' gateway loop.
    """

    state_dir: str
    workspace_root: str | None = None
    host: str = "127.0.0.1"
    port: int = 8771
    path: str = _DEFAULT_WEBHOOK_PATH
    app_id: str = ""
    app_secret: str = ""
    domain: str = "feishu"
    api_base_url: str | None = None
    verification_token: str = ""
    encrypt_key: str = ""
    allowed_users: tuple[str, ...] = ()
    require_mention: bool = True
    bot_open_id: str = ""
    bot_name: str = ""
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
class FeishuInboundMessage:
    event_id: str
    message_id: str
    chat_id: str
    chat_type: str
    text: str
    sender_type: str
    sender_ids: tuple[str, ...]
    mentions: tuple[dict[str, str], ...]


class FeishuApiError(MnemoError):
    pass


class FeishuClient:
    def __init__(self, config: FeishuChannelConfig) -> None:
        self.config = config
        self._token = ""
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def send_text(self, chat_id: str, text: str) -> None:
        if not self.config.app_id or not self.config.app_secret:
            raise FeishuApiError("FEISHU_APP_ID and FEISHU_APP_SECRET are required to send replies")
        for chunk in _split_text(text or "（空响应）", _TEXT_CHUNK_SIZE):
            self._post(
                "/open-apis/im/v1/messages",
                {"receive_id_type": "chat_id"},
                {
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": dumps({"text": chunk}),
                },
            )

    def _tenant_access_token(self) -> str:
        with self._token_lock:
            now = time.time()
            if self._token and now < self._token_expires_at:
                return self._token
            payload = self._request_json(
                "POST",
                "/open-apis/auth/v3/tenant_access_token/internal",
                {},
                {
                    "app_id": self.config.app_id,
                    "app_secret": self.config.app_secret,
                },
                token=None,
            )
            token = str(payload.get("tenant_access_token") or "")
            if not token:
                raise FeishuApiError("Feishu did not return tenant_access_token")
            expires_in = _coerce_int(payload.get("expire"), default=7200)
            self._token = token
            self._token_expires_at = now + max(60, expires_in - 60)
            return token

    def _post(self, path: str, query: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", path, query, payload, token=self._tenant_access_token())

    def _request_json(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        payload: dict[str, Any],
        *,
        token: str | None,
    ) -> dict[str, Any]:
        url = self._url(path, query)
        body = dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.config.timeout_s) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            preview = exc.read(1000).decode("utf-8", errors="replace")
            raise FeishuApiError(f"Feishu API returned HTTP {exc.code}: {_compact_api_error(preview)}") from exc
        except URLError as exc:
            raise FeishuApiError(f"Feishu API request failed: {exc.reason}") from exc
        try:
            parsed = json.loads(response_body or "{}")
        except json.JSONDecodeError as exc:
            raise FeishuApiError("Feishu API returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise FeishuApiError("Feishu API returned non-object JSON")
        code = parsed.get("code")
        if code not in (None, 0):
            message = str(parsed.get("msg") or parsed.get("message") or code)
            raise FeishuApiError(f"Feishu API error {code}: {message}")
        return parsed

    def _url(self, path: str, query: dict[str, str]) -> str:
        base = (self.config.api_base_url or "").strip()
        if not base:
            base = _LARK_API_BASE_URL if self.config.domain == "lark" else _FEISHU_API_BASE_URL
        suffix = path if path.startswith("/") else f"/{path}"
        if query:
            return f"{base.rstrip('/')}{suffix}?{urlencode(query)}"
        return f"{base.rstrip('/')}{suffix}"


class FeishuChannelService:
    def __init__(self, config: FeishuChannelConfig, client: FeishuClient | None = None) -> None:
        self.config = config
        self.client = client or FeishuClient(config)
        self._seen: dict[str, float] = {}
        self._seen_lock = threading.Lock()
        self._chat_locks: dict[str, threading.Lock] = {}
        self._chat_locks_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._threads_lock = threading.Lock()
        self._session_store = _FeishuSessionStore(config.state_dir)
        StateStore(config.state_dir).initialize()

    def handle_webhook(self, headers: dict[str, str], body_bytes: bytes) -> tuple[HTTPStatus, dict[str, Any] | str]:
        if len(body_bytes) > _DEFAULT_BODY_LIMIT_BYTES:
            return HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body too large"
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return HTTPStatus.BAD_REQUEST, {"code": 400, "msg": "invalid json"}
        if not isinstance(payload, dict):
            return HTTPStatus.BAD_REQUEST, {"code": 400, "msg": "request body must be an object"}

        if payload.get("type") == "url_verification":
            return HTTPStatus.OK, {"challenge": str(payload.get("challenge") or "")}

        if self.config.verification_token:
            header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
            incoming = str(header.get("token") or payload.get("token") or "")
            if not incoming or not hmac.compare_digest(incoming, self.config.verification_token):
                return HTTPStatus.UNAUTHORIZED, "Invalid verification token"

        if self.config.encrypt_key and not _is_signature_valid(headers, body_bytes, self.config.encrypt_key):
            return HTTPStatus.UNAUTHORIZED, "Invalid signature"

        if payload.get("encrypt"):
            return HTTPStatus.BAD_REQUEST, {"code": 400, "msg": "encrypted webhook payloads are not supported"}

        message = _extract_inbound_message(payload)
        if message is None:
            return HTTPStatus.OK, {"code": 0, "msg": "ignored"}
        if self._is_duplicate(message):
            return HTTPStatus.OK, {"code": 0, "msg": "duplicate"}
        if not self._is_allowed(message):
            return HTTPStatus.OK, {"code": 0, "msg": "ignored"}
        self._process_in_background(message)
        return HTTPStatus.OK, {"code": 0, "msg": "ok"}

    def wait_for_idle(self, timeout_s: float = 5.0) -> bool:
        deadline = time.time() + timeout_s
        while True:
            with self._threads_lock:
                threads = list(self._threads)
            if not threads:
                return True
            remaining = max(0.0, deadline - time.time())
            if remaining <= 0:
                return False
            threads[0].join(timeout=remaining)
            with self._threads_lock:
                self._threads = [thread for thread in self._threads if thread.is_alive()]

    def _is_duplicate(self, message: FeishuInboundMessage) -> bool:
        key = message.event_id or message.message_id
        if not key:
            return False
        now = time.time()
        with self._seen_lock:
            expired = [item for item, seen_at in self._seen.items() if now - seen_at > _DEDUP_TTL_SECONDS]
            for item in expired:
                self._seen.pop(item, None)
            if key in self._seen:
                return True
            self._seen[key] = now
            return False

    def _is_allowed(self, message: FeishuInboundMessage) -> bool:
        if message.sender_type in {"bot", "app"}:
            return False
        allowed = {item for item in self.config.allowed_users if item}
        if allowed and not allowed.intersection(message.sender_ids):
            return False
        if message.chat_type != "p2p" and self.config.require_mention:
            if self.config.bot_open_id or self.config.bot_name:
                return any(
                    (self.config.bot_open_id and mention.get("open_id") == self.config.bot_open_id)
                    or (self.config.bot_name and mention.get("name") == self.config.bot_name)
                    for mention in message.mentions
                )
        return True

    def _process_in_background(self, message: FeishuInboundMessage) -> None:
        thread = threading.Thread(target=self._process_message, args=(message,), daemon=True)
        with self._threads_lock:
            self._threads.append(thread)
        thread.start()

    def _process_message(self, message: FeishuInboundMessage) -> None:
        lock = self._chat_lock(message.chat_id)
        with lock:
            try:
                result = self._run_mnemo(message)
                self.client.send_text(message.chat_id, result.response)
            except Exception as exc:
                try:
                    self.client.send_text(message.chat_id, f"Mnemo 处理失败：{exc}")
                except Exception:
                    pass
            finally:
                with self._threads_lock:
                    self._threads = [thread for thread in self._threads if thread.is_alive()]

    def _chat_lock(self, chat_id: str) -> threading.Lock:
        with self._chat_locks_lock:
            lock = self._chat_locks.get(chat_id)
            if lock is None:
                lock = threading.Lock()
                self._chat_locks[chat_id] = lock
            return lock

    def _run_mnemo(self, message: FeishuInboundMessage):
        conversation_id = self._session_store.conversation_id(message.chat_id)
        request = RunRequest(
            message=message.text,
            state_dir=self.config.state_dir,
            conversation_id=conversation_id,
            workspace_root=str(resolve_workspace_root(self.config.workspace_root, self.config.state_dir)),
        )
        if self.config.provider == "local":
            result = run_local(request)
        elif self.config.provider == "openai-compatible":
            if not self.config.base_url or not self.config.model:
                raise MnemoError("openai-compatible provider requires base_url and model")
            result = run_provider(request, _openai_adapter(self.config), max_tool_rounds=self.config.max_tool_rounds)
        elif self.config.provider == "anthropic":
            if not self.config.model:
                raise MnemoError("anthropic provider requires model")
            result = run_provider(request, _anthropic_adapter(self.config), max_tool_rounds=self.config.max_tool_rounds)
        else:
            raise MnemoError(f"unsupported provider: {self.config.provider}")
        self._session_store.record(message.chat_id, result.conversation_id)
        return result


class FeishuHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self) -> None:
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name = str(self.server_address[0])
        self.server_port = int(self.server_address[1])


def build_feishu_server(config: FeishuChannelConfig) -> FeishuHTTPServer:
    config = _resolved_channel_config(config)
    service = FeishuChannelService(config)
    handler = _handler_for(config, service)
    server = FeishuHTTPServer((config.host, config.port), handler)
    server.feishu_service = service  # type: ignore[attr-defined]
    return server


def serve_feishu(config: FeishuChannelConfig) -> None:
    server = build_feishu_server(config)
    config = server.feishu_service.config  # type: ignore[attr-defined]
    host, port = server.server_address
    print(f"Mnemo Feishu channel listening on http://{host}:{port}{config.path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service = getattr(server, "feishu_service", None)
        if service is not None:
            service.wait_for_idle(timeout_s=2.0)
        server.server_close()


def _handler_for(config: FeishuChannelConfig, service: FeishuChannelService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MnemoFeishu/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json({"ok": True, "channel": "feishu"})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != config.path:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = str(self.headers.get("Content-Type", "")).split(";")[0].strip().lower()
            if content_type and content_type != "application/json":
                self._send_text(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Unsupported Media Type")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json({"code": 400, "msg": "invalid content length"}, status=HTTPStatus.BAD_REQUEST)
                return
            if length > _DEFAULT_BODY_LIMIT_BYTES:
                self._send_text(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body too large")
                return
            body = self.rfile.read(length)
            status, payload = service.handle_webhook(_normalized_headers(dict(self.headers)), body)
            if isinstance(payload, dict):
                self._send_json(payload, status=status)
            else:
                self._send_text(status, payload)

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, status: HTTPStatus, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    return Handler


class _FeishuSessionStore:
    def __init__(self, state_dir: str | Path) -> None:
        self.path = Path(state_dir).expanduser() / "channels" / "feishu_sessions.json"
        self._lock = threading.Lock()

    def conversation_id(self, chat_id: str) -> str | None:
        return self._read().get(chat_id)

    def record(self, chat_id: str, conversation_id: str) -> None:
        if not chat_id or not conversation_id:
            return
        with self._lock:
            data = self._read()
            data[chat_id] = conversation_id
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".feishu_sessions.", dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, sort_keys=True)
                    handle.write("\n")
                os.replace(tmp_name, self.path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)

    def _read(self) -> dict[str, str]:
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(key): str(value) for key, value in parsed.items() if key and value}


def _resolved_channel_config(config: FeishuChannelConfig) -> FeishuChannelConfig:
    workspace = resolve_workspace_root(config.workspace_root, config.state_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    api_key = config.api_key
    api_key_env = config.api_key_env
    if api_key_env and not api_key:
        api_key = os.environ.get(api_key_env) or None
    return FeishuChannelConfig(
        **{
            **config.__dict__,
            "state_dir": str(Path(config.state_dir).expanduser()),
            "workspace_root": str(workspace),
            "path": _normalize_path(config.path),
            "domain": config.domain if config.domain == "lark" else "feishu",
            "api_key": api_key,
            "api_key_env": api_key_env,
            "max_tool_rounds": max(1, min(int(config.max_tool_rounds), 64)),
        }
    )


def _extract_inbound_message(payload: dict[str, Any]) -> FeishuInboundMessage | None:
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    if str(header.get("event_type") or "") != "im.message.receive_v1":
        return None
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    chat_id = str(message.get("chat_id") or "")
    if not chat_id:
        return None
    text = _message_text(message)
    if not text:
        return None
    sender_ids = _sender_ids(sender)
    return FeishuInboundMessage(
        event_id=str(header.get("event_id") or message.get("message_id") or ""),
        message_id=str(message.get("message_id") or ""),
        chat_id=chat_id,
        chat_type=str(message.get("chat_type") or ""),
        text=text,
        sender_type=str(sender.get("sender_type") or ""),
        sender_ids=sender_ids,
        mentions=_mentions(message),
    )


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    parsed: Any = content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"text": content}
    if not isinstance(parsed, dict):
        return ""
    text = str(parsed.get("text") or "")
    text = _strip_at_tags(text)
    return " ".join(text.split()).strip()


def _strip_at_tags(text: str) -> str:
    result = []
    index = 0
    while index < len(text):
        start = text.find("<at ", index)
        if start == -1:
            result.append(text[index:])
            break
        result.append(text[index:start])
        end = text.find("</at>", start)
        if end == -1:
            break
        index = end + len("</at>")
    return "".join(result)


def _sender_ids(sender: dict[str, Any]) -> tuple[str, ...]:
    sender_id = sender.get("sender_id") if isinstance(sender.get("sender_id"), dict) else {}
    values = [
        sender_id.get("open_id"),
        sender_id.get("user_id"),
        sender_id.get("union_id"),
    ]
    return tuple(str(value) for value in values if value)


def _mentions(message: dict[str, Any]) -> tuple[dict[str, str], ...]:
    raw_mentions = message.get("mentions")
    if not isinstance(raw_mentions, list):
        return ()
    mentions: list[dict[str, str]] = []
    for item in raw_mentions:
        if not isinstance(item, dict):
            continue
        mention_id = item.get("id") if isinstance(item.get("id"), dict) else {}
        mentions.append(
            {
                "open_id": str(mention_id.get("open_id") or ""),
                "user_id": str(mention_id.get("user_id") or ""),
                "name": str(item.get("name") or ""),
            }
        )
    return tuple(mentions)


def _is_signature_valid(headers: dict[str, str], body_bytes: bytes, encrypt_key: str) -> bool:
    timestamp = headers.get("x-lark-request-timestamp", "")
    nonce = headers.get("x-lark-request-nonce", "")
    signature = headers.get("x-lark-signature", "")
    if not timestamp or not nonce or not signature:
        return False
    content = f"{timestamp}{nonce}{encrypt_key}{body_bytes.decode('utf-8', errors='replace')}"
    computed = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return hmac.compare_digest(computed, signature)


def _openai_adapter(config: FeishuChannelConfig) -> OpenAIProviderAdapter:
    return OpenAIProviderAdapter(
        ProviderConfig(
            base_url=config.base_url or "",
            model=config.model or "",
            api_key=config.api_key,
            timeout_s=config.timeout_s,
            retry_count=config.retry_count,
            retry_backoff_s=config.retry_backoff_s,
        )
    )


def _anthropic_adapter(config: FeishuChannelConfig) -> AnthropicProviderAdapter:
    return AnthropicProviderAdapter(
        ProviderConfig(
            base_url=config.base_url or "https://api.anthropic.com/v1",
            model=config.model or "",
            api_key=config.api_key,
            timeout_s=config.timeout_s,
            retry_count=config.retry_count,
            retry_backoff_s=config.retry_backoff_s,
        )
    )


def _split_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def _normalize_path(path: str) -> str:
    value = str(path or _DEFAULT_WEBHOOK_PATH).strip()
    return value if value.startswith("/") else f"/{value}"


def _normalized_headers(headers: dict[str, str]) -> dict[str, str]:
    return {str(key).casefold(): str(value) for key, value in headers.items()}


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact_api_error(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return " ".join(text.split())[:240]
    if isinstance(parsed, dict):
        for key in ("msg", "message", "error"):
            if parsed.get(key):
                return str(parsed[key])[:240]
    return " ".join(text.split())[:240]
