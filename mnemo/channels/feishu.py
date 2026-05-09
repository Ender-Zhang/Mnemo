from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from ..core.config import DEFAULT_MAX_TOOL_ROUNDS
from ..core.errors import MnemoError
from ..core.jsonutil import dumps
from ..core.models import ChatEvent, RunRequest
from ..core.workspace import resolve_workspace_root
from ..providers import AnthropicProviderAdapter, OpenAIProviderAdapter, ProviderConfig
from ..runtime import run_local, run_provider, stream_local, stream_provider
from ..storage import StateStore


_DEFAULT_WEBHOOK_PATH = "/feishu/webhook"
_DEFAULT_BODY_LIMIT_BYTES = 1_000_000
_DEDUP_TTL_SECONDS = 24 * 60 * 60
_FEISHU_API_BASE_URL = "https://open.feishu.cn"
_LARK_API_BASE_URL = "https://open.larksuite.com"
_FEISHU_ACCOUNTS_BASE_URL = "https://accounts.feishu.cn"
_LARK_ACCOUNTS_BASE_URL = "https://accounts.larksuite.com"
_FEISHU_REGISTRATION_PATH = "/oauth/v1/app/registration"
_ONBOARD_REQUEST_TIMEOUT_S = 10.0
_TEXT_CHUNK_SIZE = 3900
_POST_CONTENT_LIMIT_BYTES = 28_000
_POST_MARKDOWN_BLOCK_LIMIT = 3500
_SAVED_CONFIG_VERSION = "mnemo.feishu.channel.v1"
_FEISHU_ACK_EMOJI_TYPE = "THINKING"
_FEISHU_STREAM_START_TEXT = "\u200b"
_FEISHU_STREAM_SUFFIX = "\n\n_生成中..._"
_FEISHU_STREAM_EDIT_INTERVAL_S = 1.0
_FEISHU_STREAM_EDIT_MIN_CHARS = 120
_FEISHU_STREAM_MAX_PARTIAL_EDITS = 19
_FEISHU_STREAM_CARD_ELEMENT_ID = "content"
_FEISHU_STREAM_CARD_SUMMARY_LIMIT = 120

try:
    import lark_oapi as _lark_oapi  # type: ignore[import-not-found]
    from lark_oapi.core.const import FEISHU_DOMAIN as _SDK_FEISHU_DOMAIN  # type: ignore[import-not-found]
    from lark_oapi.core.const import LARK_DOMAIN as _SDK_LARK_DOMAIN  # type: ignore[import-not-found]
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler as _EventDispatcherHandler  # type: ignore[import-not-found]
    from lark_oapi.ws import Client as _FeishuWSClient  # type: ignore[import-not-found]

    _FEISHU_WS_AVAILABLE = True
except Exception:
    _lark_oapi = None
    _SDK_FEISHU_DOMAIN = None
    _SDK_LARK_DOMAIN = None
    _EventDispatcherHandler = None
    _FeishuWSClient = None
    _FEISHU_WS_AVAILABLE = False

try:
    import qrcode as _qrcode_mod  # type: ignore[import-not-found]
    from qrcode.image.svg import SvgPathImage as _SvgPathImage  # type: ignore[import-not-found]
except Exception:
    _qrcode_mod = None
    _SvgPathImage = None


@dataclass(frozen=True)
class FeishuChannelConfig:
    """Dependency-free Feishu/Lark webhook channel config.

    Acknowledgement: this transport borrows the boundary shape from
    NousResearch Hermes Agent's Feishu gateway implementation: URL
    verification before auth, verification-token and signature checks,
    callback deduplication, per-chat serialization, and background handling.
    The implementation here is Mnemo-specific and routes into Mnemo runtime
    services instead of copying Hermes' gateway loop.

    Feishu streaming cards follow Feishu's official PersonalAgent guidance
    and OpenClaw's `channels.feishu.streaming=true` behavior at the API
    boundary, while keeping Mnemo's runtime loop local to this project.
    """

    state_dir: str
    workspace_root: str | None = None
    host: str = "127.0.0.1"
    port: int = 8771
    path: str = _DEFAULT_WEBHOOK_PATH
    app_id: str = ""
    app_secret: str = ""
    domain: str = "feishu"
    connection: str = "webhook"
    api_base_url: str | None = None
    verification_token: str = ""
    encrypt_key: str = ""
    allowed_users: tuple[str, ...] = ()
    require_mention: bool = True
    bot_open_id: str = ""
    bot_name: str = ""
    streaming: bool = True
    footer_status: bool = True
    footer_elapsed: bool = True
    thread_session: bool = True
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
class FeishuQrOnboardSession:
    session_id: str
    device_code: str
    qr_url: str
    user_code: str
    interval_s: int
    expires_at: float
    domain: str = "feishu"

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "qr_url": self.qr_url,
            "qr_svg_b64": _qr_svg_b64(self.qr_url),
            "user_code": self.user_code,
            "interval_s": self.interval_s,
            "expires_at": self.expires_at,
            "domain": self.domain,
        }


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
    root_id: str = ""
    parent_id: str = ""
    thread_id: str = ""


@dataclass
class FeishuStreamingCard:
    card_id: str
    message_id: str
    chat_id: str
    sequence: int = 1
    content: str = ""
    started_at: float = 0.0


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

    def send_markdown(self, chat_id: str, markdown: str) -> list[str]:
        if not self.config.app_id or not self.config.app_secret:
            raise FeishuApiError("FEISHU_APP_ID and FEISHU_APP_SECRET are required to send replies")
        text = str(markdown or "").strip() or "（空响应）"
        sent_any = False
        message_ids: list[str] = []
        try:
            for content in _feishu_markdown_post_payloads(text, markdown_tag=True):
                message_ids.append(self._send_post(chat_id, content))
                sent_any = True
        except FeishuApiError:
            if sent_any:
                raise
            message_ids = []
            for content in _feishu_markdown_post_payloads(text, markdown_tag=False):
                message_ids.append(self._send_post(chat_id, content))
        return message_ids

    def replace_markdown(self, message_id: str, chat_id: str, markdown: str) -> list[str]:
        if not self.config.app_id or not self.config.app_secret:
            raise FeishuApiError("FEISHU_APP_ID and FEISHU_APP_SECRET are required to send replies")
        text = str(markdown or "").strip() or "（空响应）"
        payloads = _feishu_markdown_post_payloads(text, markdown_tag=True)
        try:
            self._update_post(message_id, payloads[0])
        except FeishuApiError:
            payloads = _feishu_markdown_post_payloads(text, markdown_tag=False)
            self._update_post(message_id, payloads[0])
        message_ids = [message_id]
        for content in payloads[1:]:
            message_ids.append(self._send_post(chat_id, content))
        return message_ids

    def start_streaming_card(
        self,
        chat_id: str,
        reply_to_message_id: str = "",
        *,
        reply_in_thread: bool = False,
    ) -> FeishuStreamingCard:
        if not self.config.app_id or not self.config.app_secret:
            raise FeishuApiError("FEISHU_APP_ID and FEISHU_APP_SECRET are required to send replies")
        card_id = self._create_streaming_card(_FEISHU_STREAM_START_TEXT)
        message_id = (
            self._reply_interactive_card(reply_to_message_id, card_id, reply_in_thread=reply_in_thread)
            if reply_to_message_id
            else ""
        )
        if not message_id:
            message_id = self._send_interactive_card(chat_id, card_id)
        return FeishuStreamingCard(card_id=card_id, message_id=message_id, chat_id=chat_id, started_at=time.time())

    def update_streaming_card(self, card: FeishuStreamingCard, markdown: str) -> None:
        text = str(markdown or "").strip() or _FEISHU_STREAM_START_TEXT
        card.sequence += 1
        self._put(
            f"/open-apis/cardkit/v1/cards/{card.card_id}/elements/{_FEISHU_STREAM_CARD_ELEMENT_ID}/content",
            {},
            {
                "content": text,
                "sequence": card.sequence,
                "uuid": _streaming_card_uuid(card.card_id, card.sequence),
            },
        )
        card.content = text

    def close_streaming_card(self, card: FeishuStreamingCard, markdown: str, *, is_error: bool = False) -> None:
        text = str(markdown or "").strip() or "（空响应）"
        if text != card.content:
            self.update_streaming_card(card, text)
        elapsed_ms = _elapsed_ms_since(card.started_at)
        card.sequence += 1
        self._patch(
            f"/open-apis/cardkit/v1/cards/{card.card_id}/settings",
            {},
            {
                "settings": dumps(
                    {
                        "config": {
                            "streaming_mode": False,
                            "summary": {"content": _streaming_card_summary(text)},
                        }
                    }
                ),
                "sequence": card.sequence,
                "uuid": _streaming_card_uuid(card.card_id, card.sequence),
            },
        )
        if self.config.footer_status or self.config.footer_elapsed:
            try:
                self._update_streaming_card_entity(card, text, elapsed_ms=elapsed_ms, is_error=is_error)
            except FeishuApiError:
                pass

    def add_reaction(self, message_id: str, emoji_type: str = _FEISHU_ACK_EMOJI_TYPE) -> str:
        if not self.config.app_id or not self.config.app_secret:
            raise FeishuApiError("FEISHU_APP_ID and FEISHU_APP_SECRET are required to add reactions")
        if not message_id:
            return ""
        response = self._post(
            f"/open-apis/im/v1/messages/{message_id}/reactions",
            {},
            {"reaction_type": {"emoji_type": emoji_type}},
        )
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        return str(data.get("reaction_id") or "")

    def _send_post(self, chat_id: str, content: dict[str, Any]) -> str:
        response = self._post(
            "/open-apis/im/v1/messages",
            {"receive_id_type": "chat_id"},
            {
                "receive_id": chat_id,
                "msg_type": "post",
                "content": dumps(content),
            },
        )
        return _message_id_from_response(response)

    def _create_streaming_card(self, markdown: str) -> str:
        response = self._post(
            "/open-apis/cardkit/v1/cards",
            {},
            {
                "type": "card_json",
                "data": dumps(_streaming_card_payload(markdown, self.config)),
            },
        )
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        card_id = str(data.get("card_id") or "")
        if not card_id:
            raise FeishuApiError("Feishu did not return card_id for streaming card")
        return card_id

    def _send_interactive_card(self, chat_id: str, card_id: str) -> str:
        response = self._post(
            "/open-apis/im/v1/messages",
            {"receive_id_type": "chat_id"},
            {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": dumps(_interactive_card_content(card_id)),
            },
        )
        return _message_id_from_response(response)

    def _update_streaming_card_entity(
        self,
        card: FeishuStreamingCard,
        markdown: str,
        *,
        elapsed_ms: int,
        is_error: bool,
    ) -> None:
        card.sequence += 1
        self._put(
            f"/open-apis/cardkit/v1/cards/{card.card_id}",
            {},
            {
                "card": {
                    "type": "card_json",
                    "data": dumps(
                        _streaming_card_payload(
                            markdown,
                            self.config,
                            status="error" if is_error else "complete",
                            elapsed_ms=elapsed_ms,
                        )
                    ),
                },
                "sequence": card.sequence,
                "uuid": _streaming_card_uuid(card.card_id, card.sequence),
            },
        )
        card.content = markdown

    def _reply_interactive_card(self, message_id: str, card_id: str, *, reply_in_thread: bool = False) -> str:
        if not message_id:
            return ""
        payload: dict[str, Any] = {
            "msg_type": "interactive",
            "content": dumps(_interactive_card_content(card_id)),
        }
        if reply_in_thread:
            payload["reply_in_thread"] = True
        response = self._post(
            f"/open-apis/im/v1/messages/{message_id}/reply",
            {},
            payload,
        )
        return _message_id_from_response(response)

    def _update_post(self, message_id: str, content: dict[str, Any]) -> None:
        self._put(
            f"/open-apis/im/v1/messages/{message_id}",
            {},
            {
                "msg_type": "post",
                "content": dumps(content),
            },
        )

    def bot_info(self) -> dict[str, str]:
        payload = self._request_json("GET", "/open-apis/bot/v3/info", {}, None, token=self._tenant_access_token())
        bot = payload.get("bot") if isinstance(payload.get("bot"), dict) else None
        if bot is None:
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            bot = data.get("bot") if isinstance(data.get("bot"), dict) else {}
        return {
            "bot_name": str(bot.get("app_name") or bot.get("bot_name") or ""),
            "bot_open_id": str(bot.get("open_id") or ""),
        }

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

    def _put(self, path: str, query: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("PUT", path, query, payload, token=self._tenant_access_token())

    def _patch(self, path: str, query: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("PATCH", path, query, payload, token=self._tenant_access_token())

    def _request_json(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        payload: dict[str, Any] | None,
        *,
        token: str | None,
    ) -> dict[str, Any]:
        url = self._url(path, query)
        body = dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Mnemo/0.1 FeishuChannel",
        }
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
        result = self.enqueue_message(message)
        return HTTPStatus.OK, {"code": 0, "msg": result}

    def enqueue_message(self, message: FeishuInboundMessage) -> str:
        if self._is_duplicate(message):
            return "duplicate"
        if not self._is_allowed(message):
            return "ignored"
        self._process_in_background(message)
        return "ok"

    def handle_websocket_event(self, event_data: Any) -> str:
        message = _extract_inbound_message_from_sdk_event(event_data)
        if message is None:
            return "ignored"
        return self.enqueue_message(message)

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
        self._safe_add_reaction(message)
        lock = self._chat_lock(self._session_key(message))
        with lock:
            reply_message_id = ""
            streaming_card: FeishuStreamingCard | None = None
            try:
                if self.config.streaming:
                    streaming_card = self._try_start_streaming_card(message)
                if streaming_card is not None:
                    response = self._stream_reply(message, self._streaming_card_partial_updater(streaming_card))
                    self._finalize_streaming_card(streaming_card, response)
                else:
                    reply_ids = self.client.send_markdown(message.chat_id, _FEISHU_STREAM_START_TEXT)
                    reply_message_id = reply_ids[0] if reply_ids else ""
                    response = self._stream_reply(
                        message,
                        lambda current: self._safe_replace_streaming_markdown(
                            reply_message_id, message.chat_id, current
                        ),
                    )
                    self._finalize_reply(message.chat_id, reply_message_id, response)
            except Exception as exc:
                failure = f"Mnemo 处理失败：{exc}"
                if streaming_card is not None:
                    self._send_streaming_card_failure(streaming_card, failure)
                else:
                    self._send_failure_reply(message.chat_id, reply_message_id, failure)
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

    def _safe_add_reaction(self, message: FeishuInboundMessage) -> None:
        try:
            self.client.add_reaction(message.message_id)
        except Exception:
            pass

    def _try_start_streaming_card(self, message: FeishuInboundMessage) -> FeishuStreamingCard | None:
        try:
            return self.client.start_streaming_card(
                message.chat_id,
                reply_to_message_id=message.message_id,
                reply_in_thread=self._reply_in_thread(message),
            )
        except Exception:
            return None

    def _stream_reply(
        self,
        message: FeishuInboundMessage,
        update_partial: Callable[[str], bool],
    ) -> str:
        parts: list[str] = []
        final_response = ""
        conversation_id = ""
        last_sent = ""
        last_sent_at = 0.0
        partial_edits = 0
        for event in self._stream_mnemo_events(message):
            if event.type == "assistant.delta":
                delta = _event_text(event)
                if delta:
                    parts.append(delta)
            elif event.type == "assistant.message":
                final_response = _event_text(event) or final_response
            elif event.type == "run.completed":
                final_response = _completed_response(event) or final_response
                conversation_id = _completed_conversation_id(event) or event.conversation_id or conversation_id

            current = final_response or "".join(parts)
            if (
                current
                and partial_edits < _FEISHU_STREAM_MAX_PARTIAL_EDITS
                and _should_update_stream(current, last_sent=last_sent, last_sent_at=last_sent_at)
            ):
                if update_partial(current):
                    last_sent = current
                    last_sent_at = time.time()
                    partial_edits += 1

        response = final_response or "".join(parts) or "（空响应）"
        if conversation_id:
            self._session_store.record(self._session_key(message), conversation_id)
        return response

    def _safe_replace_streaming_markdown(self, message_id: str, chat_id: str, markdown: str) -> bool:
        if not message_id:
            return False
        try:
            self.client.replace_markdown(message_id, chat_id, _streaming_markdown_preview(markdown))
            return True
        except Exception:
            return False

    def _streaming_card_partial_updater(self, card: FeishuStreamingCard) -> Callable[[str], bool]:
        def update(markdown: str) -> bool:
            try:
                self.client.update_streaming_card(card, markdown)
                return True
            except Exception:
                return False

        return update

    def _finalize_streaming_card(self, card: FeishuStreamingCard, markdown: str) -> None:
        try:
            self.client.close_streaming_card(card, markdown)
            return
        except Exception:
            pass
        try:
            self.client.send_markdown(card.chat_id, markdown)
        except Exception:
            pass

    def _send_streaming_card_failure(self, card: FeishuStreamingCard, text: str) -> None:
        try:
            self.client.close_streaming_card(card, text, is_error=True)
            return
        except Exception:
            pass
        try:
            self.client.send_text(card.chat_id, text)
        except Exception:
            pass

    def _finalize_reply(self, chat_id: str, message_id: str, markdown: str) -> None:
        if message_id:
            try:
                self.client.replace_markdown(message_id, chat_id, markdown)
                return
            except Exception:
                pass
        self.client.send_markdown(chat_id, markdown)

    def _send_failure_reply(self, chat_id: str, message_id: str, text: str) -> None:
        if message_id:
            try:
                self.client.replace_markdown(message_id, chat_id, text)
                return
            except Exception:
                pass
        try:
            self.client.send_text(chat_id, text)
        except Exception:
            pass

    def _mnemo_request(self, message: FeishuInboundMessage) -> RunRequest:
        conversation_id = self._session_store.conversation_id(self._session_key(message))
        return RunRequest(
            message=message.text,
            state_dir=self.config.state_dir,
            conversation_id=conversation_id,
            workspace_root=str(resolve_workspace_root(self.config.workspace_root, self.config.state_dir)),
        )

    def _run_mnemo(self, message: FeishuInboundMessage):
        request = self._mnemo_request(message)
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
        self._session_store.record(self._session_key(message), result.conversation_id)
        return result

    def _session_key(self, message: FeishuInboundMessage) -> str:
        thread_id = _message_thread_id(message)
        if self.config.thread_session and message.chat_type != "p2p" and thread_id:
            return f"{message.chat_id}#thread:{thread_id}"
        return message.chat_id

    def _reply_in_thread(self, message: FeishuInboundMessage) -> bool:
        return self.config.thread_session and message.chat_type != "p2p" and bool(_message_thread_id(message))

    def _stream_mnemo_events(self, message: FeishuInboundMessage):
        request = self._mnemo_request(message)
        if self.config.provider == "local":
            yield from stream_local(request)
            return
        if self.config.provider == "openai-compatible":
            if not self.config.base_url or not self.config.model:
                raise MnemoError("openai-compatible provider requires base_url and model")
            yield from stream_provider(
                request,
                _openai_adapter(self.config, stream=True),
                max_tool_rounds=self.config.max_tool_rounds,
            )
            return
        if self.config.provider == "anthropic":
            if not self.config.model:
                raise MnemoError("anthropic provider requires model")
            yield from stream_provider(
                request,
                _anthropic_adapter(self.config, stream=True),
                max_tool_rounds=self.config.max_tool_rounds,
            )
            return
        raise MnemoError(f"unsupported provider: {self.config.provider}")


class FeishuWebSocketService:
    def __init__(self, config: FeishuChannelConfig, service: FeishuChannelService | None = None) -> None:
        self.config = _resolved_channel_config(config)
        self.service = service or FeishuChannelService(self.config)

    def serve(self) -> None:
        if not _FEISHU_WS_AVAILABLE or _EventDispatcherHandler is None or _FeishuWSClient is None or _lark_oapi is None:
            raise MnemoError(
                "Feishu websocket mode requires optional dependencies. Install with: pip install 'mnemo[feishu]'"
            )
        domain = _SDK_LARK_DOMAIN if self.config.domain == "lark" else _SDK_FEISHU_DOMAIN
        event_handler = (
            _EventDispatcherHandler.builder(self.config.encrypt_key, self.config.verification_token)
            .register_p2_im_message_receive_v1(self._on_message_event)
            .register_p2_im_message_reaction_created_v1(self._on_ignored_event)
            .register_p2_im_message_reaction_deleted_v1(self._on_ignored_event)
            .build()
        )
        client = _FeishuWSClient(
            app_id=self.config.app_id,
            app_secret=self.config.app_secret,
            log_level=_lark_oapi.LogLevel.INFO,
            event_handler=event_handler,
            domain=domain,
        )
        print("Mnemo Feishu channel listening over Feishu/Lark websocket")
        try:
            client.start()
        except KeyboardInterrupt:
            pass
        finally:
            self.service.wait_for_idle(timeout_s=2.0)

    def _on_message_event(self, data: Any) -> None:
        self.service.handle_websocket_event(data)

    def _on_ignored_event(self, data: Any) -> None:
        return None

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
    if str(config.connection or "").strip().lower() == "websocket":
        FeishuWebSocketService(config).serve()
        return
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


def feishu_saved_config_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "channels" / "feishu_config.json"


def load_feishu_saved_config(state_dir: str | Path) -> dict[str, Any]:
    path = feishu_saved_config_path(state_dir)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict) or parsed.get("version") != _SAVED_CONFIG_VERSION:
        return {}
    return parsed


def save_feishu_saved_config(
    state_dir: str | Path,
    credentials: dict[str, Any],
    *,
    connection: str = "websocket",
    webhook_path: str = _DEFAULT_WEBHOOK_PATH,
    streaming: bool = True,
    footer_status: bool = True,
    footer_elapsed: bool = True,
    thread_session: bool = True,
) -> dict[str, Any]:
    app_id = str(credentials.get("app_id") or credentials.get("client_id") or "").strip()
    app_secret = str(credentials.get("app_secret") or credentials.get("client_secret") or "").strip()
    if not app_id or not app_secret:
        raise MnemoError("Feishu onboarding did not return app credentials")
    payload = {
        "version": _SAVED_CONFIG_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "domain": _normalize_domain(str(credentials.get("domain") or "feishu")),
        "connection": _normalize_connection(connection),
        "streaming": bool(streaming),
        "footer_status": bool(footer_status),
        "footer_elapsed": bool(footer_elapsed),
        "thread_session": bool(thread_session),
        "webhook_path": _normalize_path(webhook_path),
        "app_id": app_id,
        "app_secret": app_secret,
        "owner_open_id": str(credentials.get("open_id") or credentials.get("owner_open_id") or ""),
        "bot_name": str(credentials.get("bot_name") or ""),
        "bot_open_id": str(credentials.get("bot_open_id") or ""),
    }
    path = feishu_saved_config_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".feishu_config.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        try:
            os.chmod(tmp_name, 0o600)
        except OSError:
            pass
        os.replace(tmp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return feishu_channel_status(state_dir)


def feishu_channel_status(state_dir: str | Path) -> dict[str, Any]:
    saved = load_feishu_saved_config(state_dir)
    configured = bool(saved.get("app_id") and saved.get("app_secret"))
    return {
        "configured": configured,
        "config_path": str(feishu_saved_config_path(state_dir)),
        "domain": str(saved.get("domain") or ""),
        "connection": str(saved.get("connection") or ""),
        "streaming": bool(saved.get("streaming", True)),
        "footer_status": bool(saved.get("footer_status", True)),
        "footer_elapsed": bool(saved.get("footer_elapsed", True)),
        "thread_session": bool(saved.get("thread_session", True)),
        "webhook_path": str(saved.get("webhook_path") or _DEFAULT_WEBHOOK_PATH),
        "app_id": _mask_secret(str(saved.get("app_id") or "")),
        "owner_open_id": str(saved.get("owner_open_id") or ""),
        "bot_name": str(saved.get("bot_name") or ""),
        "bot_open_id": str(saved.get("bot_open_id") or ""),
    }


def start_feishu_qr_onboarding(
    *,
    domain: str = "feishu",
    accounts_base_url: str | None = None,
    now: float | None = None,
) -> FeishuQrOnboardSession:
    normalized_domain = _normalize_domain(domain)
    base_url = (accounts_base_url or _accounts_base_url(normalized_domain)).rstrip("/")
    init_response = _post_registration(base_url, {"action": "init"})
    methods = init_response.get("supported_auth_methods") if isinstance(init_response, dict) else []
    if "client_secret" not in (methods or []):
        raise MnemoError(f"Feishu QR onboarding does not support client_secret auth here: {methods}")
    begin_response = _post_registration(
        base_url,
        {
            "action": "begin",
            "archetype": "PersonalAgent",
            "auth_method": "client_secret",
            "request_user_info": "open_id",
        },
    )
    device_code = str(begin_response.get("device_code") or "")
    if not device_code:
        raise MnemoError("Feishu QR onboarding did not return a device_code")
    interval_s = max(1, _coerce_int(begin_response.get("interval"), default=5))
    expire_in = max(60, _coerce_int(begin_response.get("expire_in"), default=600))
    qr_url = str(begin_response.get("verification_uri_complete") or "")
    if not qr_url:
        raise MnemoError("Feishu QR onboarding did not return a verification URL")
    separator = "&" if "?" in qr_url else "?"
    qr_url = f"{qr_url}{separator}from=mnemo&tp=mnemo"
    return FeishuQrOnboardSession(
        session_id=f"feishu_onboard_{uuid.uuid4().hex}",
        device_code=device_code,
        qr_url=qr_url,
        user_code=str(begin_response.get("user_code") or ""),
        interval_s=interval_s,
        expires_at=(now if now is not None else time.time()) + expire_in,
        domain=normalized_domain,
    )


def poll_feishu_qr_onboarding(
    session: FeishuQrOnboardSession,
    *,
    state_dir: str | Path | None = None,
    accounts_base_url: str | None = None,
    api_base_url: str | None = None,
    now: float | None = None,
    save: bool = False,
) -> dict[str, Any]:
    current_time = now if now is not None else time.time()
    if current_time >= session.expires_at:
        return {"status": "expired", "message": "Feishu QR onboarding expired"}
    base_url = (accounts_base_url or _accounts_base_url(session.domain)).rstrip("/")
    response = _post_registration(base_url, {"action": "poll", "device_code": session.device_code, "tp": "ob_app"})
    user_info = response.get("user_info") if isinstance(response.get("user_info"), dict) else {}
    domain = _normalize_domain(str(user_info.get("tenant_brand") or session.domain))
    if domain != session.domain and not response.get("client_id") and accounts_base_url is None:
        response = _post_registration(
            _accounts_base_url(domain).rstrip("/"),
            {"action": "poll", "device_code": session.device_code, "tp": "ob_app"},
        )
        user_info = response.get("user_info") if isinstance(response.get("user_info"), dict) else {}
        domain = _normalize_domain(str(user_info.get("tenant_brand") or domain))
    if response.get("client_id") and response.get("client_secret"):
        credentials = {
            "app_id": str(response["client_id"]),
            "app_secret": str(response["client_secret"]),
            "domain": domain,
            "open_id": str(user_info.get("open_id") or ""),
        }
        credentials.update(probe_feishu_bot(credentials["app_id"], credentials["app_secret"], domain, api_base_url=api_base_url))
        public = _public_credentials(credentials)
        result: dict[str, Any] = {"status": "configured", "credentials": public}
        if save:
            if state_dir is None:
                raise MnemoError("state_dir is required when saving Feishu onboarding credentials")
            result["channel"] = save_feishu_saved_config(state_dir, credentials, connection="websocket")
        return result
    error = str(response.get("error") or "")
    if error in {"access_denied", "expired_token"}:
        return {"status": "denied" if error == "access_denied" else "expired", "message": error}
    return {"status": "pending", "retry_after_s": session.interval_s}


def run_feishu_qr_onboarding(
    *,
    state_dir: str | Path,
    domain: str = "feishu",
    timeout_s: int = 600,
) -> dict[str, Any]:
    session = start_feishu_qr_onboarding(domain=domain, now=time.time())
    session = FeishuQrOnboardSession(
        session_id=session.session_id,
        device_code=session.device_code,
        qr_url=session.qr_url,
        user_code=session.user_code,
        interval_s=session.interval_s,
        expires_at=min(session.expires_at, time.time() + max(30, timeout_s)),
        domain=session.domain,
    )
    if _print_terminal_qr(session.qr_url):
        print(f"\nScan the QR code above, or open this URL:\n{session.qr_url}\n")
    else:
        print(f"Open this URL in Feishu/Lark, or scan it from another device:\n{session.qr_url}\n")
        print("Tip: install the optional feishu extra to render a terminal QR: pip install 'mnemo[feishu]'")
    while time.time() < session.expires_at:
        result = poll_feishu_qr_onboarding(session, state_dir=state_dir, save=True)
        if result.get("status") == "configured":
            return result
        if result.get("status") in {"denied", "expired"}:
            raise MnemoError(str(result.get("message") or result["status"]))
        time.sleep(session.interval_s)
    raise MnemoError("Feishu QR onboarding timed out")


def probe_feishu_bot(app_id: str, app_secret: str, domain: str, *, api_base_url: str | None = None) -> dict[str, str]:
    try:
        config = FeishuChannelConfig(
            state_dir=str(Path(tempfile.gettempdir()) / "mnemo-feishu-probe"),
            app_id=app_id,
            app_secret=app_secret,
            domain=_normalize_domain(domain),
            api_base_url=api_base_url,
            timeout_s=_ONBOARD_REQUEST_TIMEOUT_S,
        )
        return FeishuClient(config).bot_info()
    except Exception:
        return {"bot_name": "", "bot_open_id": ""}


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
            "domain": _normalize_domain(config.domain),
            "connection": _normalize_connection(config.connection),
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
        root_id=str(message.get("root_id") or ""),
        parent_id=str(message.get("parent_id") or ""),
        thread_id=str(message.get("thread_id") or ""),
    )


def _extract_inbound_message_from_sdk_event(data: Any) -> FeishuInboundMessage | None:
    event = getattr(data, "event", None)
    header = getattr(data, "header", None)
    message = getattr(event, "message", None)
    sender = getattr(event, "sender", None)
    if message is None or sender is None:
        return None
    chat_id = str(getattr(message, "chat_id", "") or "")
    if not chat_id:
        return None
    text = _message_text(_sdk_message_dict(message))
    if not text:
        return None
    sender_ids = _sdk_sender_ids(sender)
    return FeishuInboundMessage(
        event_id=str(getattr(header, "event_id", "") or getattr(message, "message_id", "") or ""),
        message_id=str(getattr(message, "message_id", "") or ""),
        chat_id=chat_id,
        chat_type=str(getattr(message, "chat_type", "") or ""),
        text=text,
        sender_type=str(getattr(sender, "sender_type", "") or ""),
        sender_ids=sender_ids,
        mentions=_sdk_mentions(message),
        root_id=str(getattr(message, "root_id", "") or ""),
        parent_id=str(getattr(message, "parent_id", "") or ""),
        thread_id=str(getattr(message, "thread_id", "") or ""),
    )


def _sdk_message_dict(message: Any) -> dict[str, Any]:
    return {
        "content": getattr(message, "content", None),
    }


def _sdk_sender_ids(sender: Any) -> tuple[str, ...]:
    sender_id = getattr(sender, "sender_id", None)
    values = [
        getattr(sender_id, "open_id", None),
        getattr(sender_id, "user_id", None),
        getattr(sender_id, "union_id", None),
    ]
    return tuple(str(value) for value in values if value)


def _sdk_mentions(message: Any) -> tuple[dict[str, str], ...]:
    raw_mentions = getattr(message, "mentions", None)
    if not raw_mentions:
        return ()
    mentions: list[dict[str, str]] = []
    for item in raw_mentions:
        mention_id = getattr(item, "id", None)
        mentions.append(
            {
                "open_id": str(getattr(mention_id, "open_id", "") or ""),
                "user_id": str(getattr(mention_id, "user_id", "") or ""),
                "name": str(getattr(item, "name", "") or ""),
            }
        )
    return tuple(mentions)


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


def _openai_adapter(config: FeishuChannelConfig, *, stream: bool = False) -> OpenAIProviderAdapter:
    return OpenAIProviderAdapter(
        ProviderConfig(
            base_url=config.base_url or "",
            model=config.model or "",
            api_key=config.api_key,
            timeout_s=config.timeout_s,
            retry_count=config.retry_count,
            retry_backoff_s=config.retry_backoff_s,
            stream=stream,
        )
    )


def _anthropic_adapter(config: FeishuChannelConfig, *, stream: bool = False) -> AnthropicProviderAdapter:
    return AnthropicProviderAdapter(
        ProviderConfig(
            base_url=config.base_url or "https://api.anthropic.com/v1",
            model=config.model or "",
            api_key=config.api_key,
            timeout_s=config.timeout_s,
            retry_count=config.retry_count,
            retry_backoff_s=config.retry_backoff_s,
            stream=stream,
        )
    )


def _split_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def _message_id_from_response(response: dict[str, Any]) -> str:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    return str(data.get("message_id") or "")


def _interactive_card_content(card_id: str) -> dict[str, Any]:
    return {"type": "card", "data": {"card_id": card_id}}


def _streaming_card_payload(
    markdown: str,
    config: FeishuChannelConfig | None = None,
    *,
    status: str = "streaming",
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    text = str(markdown or "").strip() or _FEISHU_STREAM_START_TEXT
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "element_id": _FEISHU_STREAM_CARD_ELEMENT_ID,
            "content": text,
            "text_align": "left",
            "text_size": "normal",
            "margin": "0px 0px 0px 0px",
        }
    ]
    footer = _streaming_card_footer_element(config, status=status, elapsed_ms=elapsed_ms)
    if footer:
        elements.append(footer)
    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": status == "streaming",
            "summary": {"content": _streaming_card_summary(text)},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
    }


def _streaming_card_footer_element(
    config: FeishuChannelConfig | None,
    *,
    status: str,
    elapsed_ms: int | None,
) -> dict[str, Any] | None:
    if config is None or status not in {"complete", "error"}:
        return None
    zh_parts: list[str] = []
    en_parts: list[str] = []
    if config.footer_status:
        if status == "error":
            zh_parts.append("出错")
            en_parts.append("Error")
        else:
            zh_parts.append("已完成")
            en_parts.append("Completed")
    if config.footer_elapsed and elapsed_ms is not None:
        elapsed = _format_elapsed_ms(elapsed_ms)
        zh_parts.append(f"耗时 {elapsed}")
        en_parts.append(f"Elapsed {elapsed}")
    if not zh_parts:
        return None
    zh_content = " · ".join(zh_parts)
    en_content = " · ".join(en_parts)
    if status == "error":
        zh_content = f"<font color='red'>{zh_content}</font>"
        en_content = f"<font color='red'>{en_content}</font>"
    return {
        "tag": "markdown",
        "content": zh_content,
        "i18n_content": {"zh_cn": zh_content, "en_us": en_content},
        "text_size": "notation",
        "margin": "8px 0px 0px 0px",
    }


def _format_elapsed_ms(elapsed_ms: int) -> str:
    seconds = max(0, elapsed_ms) / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {round(seconds % 60)}s"


def _elapsed_ms_since(started_at: float) -> int:
    if started_at <= 0:
        return 0
    return max(0, int((time.time() - started_at) * 1000))


def _streaming_card_summary(text: str) -> str:
    body = " ".join(str(text or "").split()) or "Mnemo"
    if len(body) <= _FEISHU_STREAM_CARD_SUMMARY_LIMIT:
        return body
    return body[: _FEISHU_STREAM_CARD_SUMMARY_LIMIT - 1].rstrip() + "..."


def _streaming_card_uuid(card_id: str, sequence: int) -> str:
    return f"mnemo-{card_id}-{sequence}"


def _message_thread_id(message: FeishuInboundMessage) -> str:
    return str(message.thread_id or message.root_id or message.parent_id or "").strip()


def _event_text(event: ChatEvent) -> str:
    data = event.data if isinstance(event.data, dict) else {}
    return str(data.get("text") or data.get("delta") or data.get("content") or "")


def _completed_response(event: ChatEvent) -> str:
    data = event.data if isinstance(event.data, dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    return str(result.get("response") or "")


def _completed_conversation_id(event: ChatEvent) -> str:
    data = event.data if isinstance(event.data, dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    return str(result.get("conversation_id") or "")


def _should_update_stream(text: str, *, last_sent: str, last_sent_at: float) -> bool:
    if not text or text == last_sent:
        return False
    if not last_sent:
        return True
    if len(text) - len(last_sent) >= _FEISHU_STREAM_EDIT_MIN_CHARS:
        return True
    return time.time() - last_sent_at >= _FEISHU_STREAM_EDIT_INTERVAL_S


def _streaming_markdown_preview(text: str) -> str:
    body = str(text or "").strip()
    budget = max(200, _POST_MARKDOWN_BLOCK_LIMIT - len(_FEISHU_STREAM_SUFFIX) - 20)
    if len(body) > budget:
        body = body[:budget].rstrip() + "\n..."
    return f"{body}{_FEISHU_STREAM_SUFFIX}" if body else _FEISHU_STREAM_START_TEXT


def _feishu_markdown_post_payloads(text: str, *, markdown_tag: bool) -> list[dict[str, Any]]:
    title, body = _markdown_title_and_body(text)
    segments = _markdown_segments(body or text)
    blocks = [_markdown_segment_to_post_block(segment, markdown_tag=markdown_tag) for segment in segments]
    blocks = [block for block in blocks if block]
    if not blocks:
        blocks = [[{"tag": "text", "text": "（空响应）"}]]
    payloads: list[dict[str, Any]] = []
    current: list[list[dict[str, Any]]] = []
    for block in blocks:
        trial = current + [block]
        payload = _post_payload(title, trial)
        if current and len(dumps(payload).encode("utf-8")) > _POST_CONTENT_LIMIT_BYTES:
            payloads.append(_post_payload(title, current))
            current = [block]
        else:
            current = trial
    if current:
        payloads.append(_post_payload(title, current))
    return payloads


def _post_payload(title: str, blocks: list[list[dict[str, Any]]]) -> dict[str, Any]:
    return {"zh_cn": {"title": title or "Mnemo", "content": blocks}}


def _markdown_title_and_body(text: str) -> tuple[str, str]:
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = ""
    body: list[str] = []
    removed_heading = False
    for line in lines:
        stripped = line.strip()
        if not title and stripped:
            heading = _markdown_heading_text(stripped)
            title = _plain_markdown_text(heading or stripped)[:80] or "Mnemo"
            if heading and not removed_heading:
                removed_heading = True
                continue
        body.append(line)
    return title or "Mnemo", "\n".join(body).strip()


def _markdown_segments(text: str) -> list[str]:
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            current.append(line)
            in_fence = not in_fence
            if not in_fence:
                segments.extend(_split_text("\n".join(current).strip(), _POST_MARKDOWN_BLOCK_LIMIT))
                current = []
            continue
        if not in_fence and not line.strip():
            if current:
                segments.extend(_split_text("\n".join(current).strip(), _POST_MARKDOWN_BLOCK_LIMIT))
                current = []
            continue
        current.append(line)
    if current:
        segments.extend(_split_text("\n".join(current).strip(), _POST_MARKDOWN_BLOCK_LIMIT))
    return [segment for segment in segments if segment]


def _markdown_segment_to_post_block(segment: str, *, markdown_tag: bool) -> list[dict[str, Any]]:
    if markdown_tag:
        return [{"tag": "md", "text": segment}]
    elements: list[dict[str, Any]] = []
    lines = segment.splitlines() or [segment]
    for index, line in enumerate(lines):
        if index:
            elements.append({"tag": "text", "text": "\n"})
        elements.extend(_inline_post_elements(_structural_markdown_line(line)))
    return elements


def _structural_markdown_line(line: str) -> str:
    stripped = str(line or "").strip()
    if not stripped:
        return ""
    heading = _markdown_heading_text(stripped)
    if heading:
        return heading
    if stripped.startswith(">"):
        return "｜ " + stripped.lstrip("> ").strip()
    if len(stripped) > 6 and stripped[:3].casefold() in {"- [", "* [", "+ ["}:
        marker = "☑" if stripped[3:4].casefold() == "x" else "☐"
        return f"{marker} {stripped[6:].strip()}"
    unordered = stripped[2:] if stripped[:2] in {"- ", "* ", "+ "} else ""
    if unordered:
        return "• " + unordered.strip()
    return stripped


def _markdown_heading_text(stripped: str) -> str:
    if not stripped.startswith("#"):
        return ""
    marker = len(stripped) - len(stripped.lstrip("#"))
    if 1 <= marker <= 6 and len(stripped) > marker and stripped[marker : marker + 1].isspace():
        return stripped[marker:].strip()
    return ""


def _plain_markdown_text(text: str) -> str:
    value = str(text or "")
    replacements = ("**", "__", "~~", "`", "*")
    for item in replacements:
        value = value.replace(item, "")
    return " ".join(value.split()).strip()


def _inline_post_elements(text: str) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        start = text.find("[", index)
        if start < 0:
            elements.extend(_styled_text_elements(text[index:]))
            break
        end_label = text.find("]", start + 1)
        if end_label < 0 or end_label + 1 >= len(text) or text[end_label + 1] != "(":
            elements.extend(_styled_text_elements(text[index : start + 1]))
            index = start + 1
            continue
        end_url = text.find(")", end_label + 2)
        if end_url < 0:
            elements.extend(_styled_text_elements(text[index : start + 1]))
            index = start + 1
            continue
        href = text[end_label + 2 : end_url].strip()
        label = _plain_markdown_text(text[start + 1 : end_label])
        if not href.startswith(("http://", "https://")) or not label:
            elements.extend(_styled_text_elements(text[index : end_url + 1]))
            index = end_url + 1
            continue
        elements.extend(_styled_text_elements(text[index:start]))
        elements.append({"tag": "a", "text": label, "href": href})
        index = end_url + 1
    return elements or [{"tag": "text", "text": text}]


def _styled_text_elements(text: str, style: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if not text:
        return []
    tokens = (("**", "bold"), ("__", "bold"), ("~~", "lineThrough"), ("`", "bold"), ("*", "italic"))
    best_start = -1
    best_token = ""
    best_style = ""
    for token, item_style in tokens:
        start = text.find(token)
        if start >= 0 and (best_start < 0 or start < best_start or len(token) > len(best_token)):
            best_start = start
            best_token = token
            best_style = item_style
    if best_start < 0:
        return [_post_text(text, style)] if text else []
    end = text.find(best_token, best_start + len(best_token))
    if end < 0:
        return [_post_text(text, style)]
    elements: list[dict[str, Any]] = []
    elements.extend(_styled_text_elements(text[:best_start], style))
    elements.extend(_styled_text_elements(text[best_start + len(best_token) : end], (*style, best_style)))
    elements.extend(_styled_text_elements(text[end + len(best_token) :], style))
    return elements


def _post_text(text: str, style: tuple[str, ...] = ()) -> dict[str, Any]:
    element: dict[str, Any] = {"tag": "text", "text": text}
    if style:
        element["style"] = list(dict.fromkeys(style))
    return element


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


def _accounts_base_url(domain: str) -> str:
    return _LARK_ACCOUNTS_BASE_URL if _normalize_domain(domain) == "lark" else _FEISHU_ACCOUNTS_BASE_URL


def _post_registration(base_url: str, body: dict[str, str]) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{_FEISHU_REGISTRATION_PATH}"
    request = Request(
        url,
        data=urlencode(body).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=_ONBOARD_REQUEST_TIMEOUT_S) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        if not payload:
            raise
    except URLError as exc:
        raise MnemoError(f"Feishu QR onboarding request failed: {exc.reason}") from exc
    try:
        parsed = json.loads(payload or "{}")
    except json.JSONDecodeError as exc:
        raise MnemoError("Feishu QR onboarding returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise MnemoError("Feishu QR onboarding returned non-object JSON")
    return parsed


def _normalize_domain(domain: str) -> str:
    return "lark" if str(domain or "").strip().lower() == "lark" else "feishu"


def _normalize_connection(connection: str) -> str:
    return "websocket" if str(connection or "").strip().lower() == "websocket" else "webhook"


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return f"{value[:2]}..."
    return f"{value[:6]}...{value[-4:]}"


def _public_credentials(credentials: dict[str, Any]) -> dict[str, str]:
    return {
        "app_id": _mask_secret(str(credentials.get("app_id") or "")),
        "domain": _normalize_domain(str(credentials.get("domain") or "")),
        "owner_open_id": str(credentials.get("open_id") or credentials.get("owner_open_id") or ""),
        "bot_name": str(credentials.get("bot_name") or ""),
        "bot_open_id": str(credentials.get("bot_open_id") or ""),
    }


def _qr_svg_b64(url: str) -> str:
    if not url or _qrcode_mod is None or _SvgPathImage is None:
        return ""
    try:
        image = _qrcode_mod.make(url, image_factory=_SvgPathImage)
        buffer = BytesIO()
        image.save(buffer)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        return ""


def _print_terminal_qr(url: str) -> bool:
    if not url or _qrcode_mod is None:
        return False
    try:
        qr = _qrcode_mod.QRCode()
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        return True
    except Exception:
        return False


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
