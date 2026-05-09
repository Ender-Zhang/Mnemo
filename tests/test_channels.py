from __future__ import annotations

import hashlib
import http.client
import json
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mnemo.channels import (
    FeishuChannelConfig,
    build_feishu_server,
    feishu_channel_status,
    load_feishu_saved_config,
    poll_feishu_qr_onboarding,
    save_feishu_saved_config,
    start_feishu_qr_onboarding,
)
from mnemo.core.models import ChatEvent
from mnemo.core.jsonutil import dumps


class FeishuChannelTests(unittest.TestCase):
    def test_install_script_is_parseable_and_documents_feishu(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
        completed = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        content = script.read_text(encoding="utf-8")
        self.assertIn("NousResearch Hermes Agent", content)
        self.assertIn("OpenClaw", content)
        self.assertIn("mnemo onboard", content)
        self.assertIn("mnemo channels feishu serve", content)
        self.assertIn("FEISHU_APP_ID", content)

    def test_feishu_websocket_registers_reaction_event_noops(self) -> None:
        channel = Path(__file__).resolve().parents[1] / "mnemo" / "channels" / "feishu.py"
        content = channel.read_text(encoding="utf-8")
        self.assertIn("register_p2_im_message_reaction_created_v1(self._on_ignored_event)", content)
        self.assertIn("register_p2_im_message_reaction_deleted_v1(self._on_ignored_event)", content)

    def test_feishu_webhook_challenge_and_token_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = FeishuChannelConfig(
                state_dir=tmp,
                port=0,
                app_id="cli_test",
                app_secret="secret_test",
                verification_token="verify-token",
            )
            with RunningFeishuChannel(config) as server:
                status, _, body = server.request(
                    "POST",
                    "/feishu/webhook",
                    {"type": "url_verification", "challenge": "challenge-ok"},
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body), {"challenge": "challenge-ok"})

                status, _, body = server.request("POST", "/feishu/webhook", _message_payload(token="bad-token"))
                self.assertEqual(status, 401)
                self.assertIn("Invalid verification token", body)

    def test_feishu_message_runs_mnemo_and_sends_reply_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with FakeFeishuApiServer() as api:
                config = FeishuChannelConfig(
                    state_dir=tmp,
                    port=0,
                    app_id="cli_test",
                    app_secret="secret_test",
                    verification_token="verify-token",
                    api_base_url=api.base_url,
                )
                with RunningFeishuChannel(config) as server:
                    payload = _message_payload(text="hello from feishu")
                    status, _, body = server.request("POST", "/feishu/webhook", payload)
                    self.assertEqual(status, 200, body)
                    self.assertEqual(json.loads(body), {"code": 0, "msg": "ok"})
                    self.assertTrue(server.service.wait_for_idle(timeout_s=5.0))

                    reaction_requests = api.requests_for("/open-apis/im/v1/messages/om_msg_1/reactions")
                    self.assertEqual(len(reaction_requests), 1)
                    self.assertEqual(reaction_requests[0]["body"]["reaction_type"]["emoji_type"], "THINKING")

                    send_requests = api.requests_for("/open-apis/im/v1/messages")
                    self.assertEqual(len(send_requests), 1)
                    sent = send_requests[0]["body"]
                    self.assertEqual(sent["receive_id"], "oc_chat")
                    self.assertEqual(sent["msg_type"], "post")
                    sent_content = json.loads(sent["content"])
                    self.assertIn("正在思考", sent_content["zh_cn"]["content"][0][0]["text"])

                    update_requests = api.requests_for("/open-apis/im/v1/messages/om_reply")
                    self.assertGreaterEqual(len(update_requests), 1)
                    updated = update_requests[-1]["body"]
                    self.assertEqual(updated["msg_type"], "post")
                    content = json.loads(updated["content"])
                    self.assertTrue(content["zh_cn"]["title"].startswith("已创建一次 Mnemo 运行"))
                    self.assertEqual(content["zh_cn"]["content"][0][0]["tag"], "md")
                    self.assertIn("已创建一次 Mnemo 运行", content["zh_cn"]["content"][0][0]["text"])

                    status, _, body = server.request("POST", "/feishu/webhook", payload)
                    self.assertEqual(status, 200, body)
                    self.assertEqual(json.loads(body), {"code": 0, "msg": "duplicate"})
                    self.assertTrue(server.service.wait_for_idle(timeout_s=5.0))
                    self.assertEqual(len(api.requests_for("/open-apis/im/v1/messages")), 1)
                    self.assertEqual(len(api.requests_for("/open-apis/im/v1/messages/om_msg_1/reactions")), 1)

            session_file = Path(tmp) / "channels" / "feishu_sessions.json"
            sessions = json.loads(session_file.read_text(encoding="utf-8"))
            self.assertTrue(sessions["oc_chat"].startswith("conv_"))

    def test_feishu_reply_sends_markdown_as_rich_post(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with FakeFeishuApiServer() as api:
                config = FeishuChannelConfig(
                    state_dir=tmp,
                    port=0,
                    app_id="cli_test",
                    app_secret="secret_test",
                    verification_token="verify-token",
                    api_base_url=api.base_url,
                )
                with RunningFeishuChannel(config) as server:
                    markdown = "# 今日计划\n\n- **重点** 看 [文档](https://example.com)\n\n```python\nprint(1)\n```"
                    server.service._stream_mnemo_events = lambda _message: iter(  # type: ignore[method-assign]
                        [
                            _chat_event("assistant.delta", {"text": markdown}, conversation_id="conv_markdown"),
                            _chat_event(
                                "assistant.message",
                                {"text": markdown, "final": True},
                                conversation_id="conv_markdown",
                            ),
                            _chat_event(
                                "run.completed",
                                {
                                    "status": "completed",
                                    "result": {
                                        "conversation_id": "conv_markdown",
                                        "mission_id": "mis_markdown",
                                        "run_id": "run_markdown",
                                        "response": markdown,
                                        "tool_results": [],
                                    },
                                },
                                conversation_id="conv_markdown",
                            ),
                        ]
                    )
                    status, _, body = server.request("POST", "/feishu/webhook", _message_payload(text="markdown please"))
                    self.assertEqual(status, 200, body)
                    self.assertTrue(server.service.wait_for_idle(timeout_s=5.0))

                    updated = api.requests_for("/open-apis/im/v1/messages/om_reply")[-1]["body"]
                    self.assertEqual(updated["msg_type"], "post")
                    content = json.loads(updated["content"])
                    self.assertEqual(content["zh_cn"]["title"], "今日计划")
                    blocks = content["zh_cn"]["content"]
                    self.assertEqual(blocks[0][0]["tag"], "md")
                    rendered = "\n".join(block[0]["text"] for block in blocks)
                    self.assertIn("- **重点** 看 [文档](https://example.com)", rendered)
                    self.assertIn("```python", rendered)

    def test_feishu_reply_streams_by_editing_bot_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with FakeFeishuApiServer() as api:
                config = FeishuChannelConfig(
                    state_dir=tmp,
                    port=0,
                    app_id="cli_test",
                    app_secret="secret_test",
                    verification_token="verify-token",
                    api_base_url=api.base_url,
                )
                with RunningFeishuChannel(config) as server:
                    server.service._stream_mnemo_events = lambda _message: iter(  # type: ignore[method-assign]
                        [
                            _chat_event("assistant.delta", {"text": "hello"}),
                            _chat_event("assistant.delta", {"text": " world" * 30}),
                            _chat_event(
                                "assistant.message",
                                {"text": "hello" + " world" * 30, "final": True},
                            ),
                            _chat_event(
                                "run.completed",
                                {
                                    "status": "completed",
                                    "result": {
                                        "conversation_id": "conv_stream",
                                        "mission_id": "mis_stream",
                                        "run_id": "run_stream",
                                        "response": "hello" + " world" * 30,
                                        "tool_results": [],
                                    },
                                },
                                conversation_id="conv_stream",
                            ),
                        ]
                    )
                    status, _, body = server.request("POST", "/feishu/webhook", _message_payload(text="stream please"))
                    self.assertEqual(status, 200, body)
                    self.assertTrue(server.service.wait_for_idle(timeout_s=5.0))

                    updates = api.requests_for("/open-apis/im/v1/messages/om_reply")
                    self.assertGreaterEqual(len(updates), 2)
                    first_content = json.loads(updates[0]["body"]["content"])
                    final_content = json.loads(updates[-1]["body"]["content"])
                    first_text = "\n".join(block[0]["text"] for block in first_content["zh_cn"]["content"])
                    final_text = "\n".join(block[0]["text"] for block in final_content["zh_cn"]["content"])
                    self.assertIn("生成中", first_text)
                    self.assertNotIn("生成中", final_text)
                    self.assertIn("hello world", final_text)

    def test_feishu_final_edit_failure_sends_final_reply_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with FakeFeishuApiServer() as api:
                api.fail_put = True
                config = FeishuChannelConfig(
                    state_dir=tmp,
                    port=0,
                    app_id="cli_test",
                    app_secret="secret_test",
                    verification_token="verify-token",
                    api_base_url=api.base_url,
                )
                with RunningFeishuChannel(config) as server:
                    server.service._stream_mnemo_events = lambda _message: iter(  # type: ignore[method-assign]
                        [
                            _chat_event("assistant.delta", {"text": "fallback answer"}),
                            _chat_event("assistant.message", {"text": "fallback answer", "final": True}),
                            _chat_event(
                                "run.completed",
                                {
                                    "status": "completed",
                                    "result": {
                                        "conversation_id": "conv_fallback",
                                        "mission_id": "mis_fallback",
                                        "run_id": "run_fallback",
                                        "response": "fallback answer",
                                        "tool_results": [],
                                    },
                                },
                                conversation_id="conv_fallback",
                            ),
                        ]
                    )
                    status, _, body = server.request("POST", "/feishu/webhook", _message_payload(text="fallback please"))
                    self.assertEqual(status, 200, body)
                    self.assertTrue(server.service.wait_for_idle(timeout_s=5.0))

                    sends = api.requests_for("/open-apis/im/v1/messages")
                    self.assertEqual(len(sends), 2)
                    fallback_content = json.loads(sends[-1]["body"]["content"])
                    fallback_text = "\n".join(block[0]["text"] for block in fallback_content["zh_cn"]["content"])
                    self.assertIn("fallback answer", fallback_text)

    def test_feishu_webhook_signature_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = FeishuChannelConfig(
                state_dir=tmp,
                app_id="cli_test",
                app_secret="secret_test",
                encrypt_key="encrypt-key",
            )
            server = build_feishu_server(config)
            service = server.feishu_service  # type: ignore[attr-defined]
            body = dumps({"schema": "2.0", "header": {"event_type": "unknown"}}).encode("utf-8")
            status, payload = service.handle_webhook(
                {
                    "x-lark-request-timestamp": "123",
                    "x-lark-request-nonce": "nonce",
                    "x-lark-signature": "wrong",
                },
                body,
            )
            self.assertEqual(status, 401)
            self.assertEqual(payload, "Invalid signature")

            signature = hashlib.sha256(b"123nonceencrypt-key" + body).hexdigest()
            status, payload = service.handle_webhook(
                {
                    "x-lark-request-timestamp": "123",
                    "x-lark-request-nonce": "nonce",
                    "x-lark-signature": signature,
                },
                body,
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"code": 0, "msg": "ignored"})
            self.assertTrue(service.wait_for_idle(timeout_s=5.0))
            server.server_close()

    def test_feishu_qr_onboarding_start_poll_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with FakeFeishuOnboardServer() as onboard, FakeFeishuApiServer() as api:
                session = start_feishu_qr_onboarding(accounts_base_url=onboard.base_url, now=1000.0)
                self.assertTrue(session.device_code.startswith("dc_"))
                self.assertIn("from=mnemo", session.qr_url)
                first = poll_feishu_qr_onboarding(
                    session,
                    state_dir=tmp,
                    accounts_base_url=onboard.base_url,
                    api_base_url=api.base_url,
                    now=1001.0,
                    save=True,
                )
                self.assertEqual(first["status"], "pending")
                second = poll_feishu_qr_onboarding(
                    session,
                    state_dir=tmp,
                    accounts_base_url=onboard.base_url,
                    api_base_url=api.base_url,
                    now=1002.0,
                    save=True,
                )
                self.assertEqual(second["status"], "configured")
                self.assertEqual(second["channel"]["connection"], "websocket")
                self.assertNotIn("secret_test", json.dumps(second, ensure_ascii=False))
                saved = load_feishu_saved_config(tmp)
                self.assertEqual(saved["app_id"], "cli_test")
                self.assertEqual(saved["app_secret"], "secret_test")
                self.assertEqual(saved["bot_name"], "MnemoBot")
                status = feishu_channel_status(tmp)
                self.assertEqual(status["bot_name"], "MnemoBot")
                self.assertNotIn("secret_test", json.dumps(status, ensure_ascii=False))

    def test_feishu_saved_config_requires_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                save_feishu_saved_config(tmp, {"app_id": "cli_only"})


def _message_payload(*, text: str = "hello", token: str = "verify-token") -> dict[str, Any]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "evt_1",
            "event_type": "im.message.receive_v1",
            "token": token,
        },
        "event": {
            "sender": {
                "sender_type": "user",
                "sender_id": {
                    "open_id": "ou_user",
                    "user_id": "u_user",
                    "union_id": "on_user",
                },
            },
            "message": {
                "message_id": "om_msg_1",
                "chat_id": "oc_chat",
                "chat_type": "p2p",
                "message_type": "text",
                "content": dumps({"text": text}),
            },
        },
    }


def _chat_event(
    event_type: str,
    data: dict[str, Any],
    *,
    conversation_id: str = "conv_stream",
    mission_id: str = "mis_stream",
    run_id: str = "run_stream",
) -> ChatEvent:
    return ChatEvent(
        event_id=f"evt_{event_type.replace('.', '_')}",
        type=event_type,  # type: ignore[arg-type]
        run_id=run_id,
        conversation_id=conversation_id,
        mission_id=mission_id,
        data=data,
        created_at=0.0,
    )


class RunningFeishuChannel:
    def __init__(self, config: FeishuChannelConfig) -> None:
        self.server = build_feishu_server(config)
        self.service = self.server.feishu_service  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> RunningFeishuChannel:
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.service.wait_for_idle(timeout_s=2.0)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def request(self, method: str, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, str], str]:
        host, port = self.server.server_address
        conn = http.client.HTTPConnection(host, port, timeout=5)
        body = dumps(payload)
        conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        raw_body = response.read().decode("utf-8")
        headers = {key.casefold(): value for key, value in response.getheaders()}
        conn.close()
        return response.status, headers, raw_body


class FakeFeishuApiServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.fail_put = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeFeishuApiServer:
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def requests_for(self, path: str) -> list[dict[str, Any]]:
        return [request for request in self.requests if request["path"] == path]

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                fake.requests.append({"path": path, "headers": dict(self.headers), "body": {}})
                if path == "/open-apis/bot/v3/info":
                    self._send_json({"code": 0, "bot": {"app_name": "MnemoBot", "open_id": "ou_bot"}})
                    return
                self._send_json({"code": 404, "msg": "not found"}, status=404)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                parsed = json.loads(body) if body else {}
                path = self.path.split("?", 1)[0]
                fake.requests.append({"path": path, "headers": dict(self.headers), "body": parsed})
                if path == "/open-apis/auth/v3/tenant_access_token/internal":
                    self._send_json({"code": 0, "tenant_access_token": "tenant-token", "expire": 7200})
                    return
                if path == "/open-apis/im/v1/messages":
                    self._send_json({"code": 0, "data": {"message_id": "om_reply"}})
                    return
                if path == "/open-apis/im/v1/messages/om_msg_1/reactions":
                    self._send_json({"code": 0, "data": {"reaction_id": "reaction_1"}})
                    return
                self._send_json({"code": 404, "msg": "not found"}, status=404)

            def do_PUT(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                parsed = json.loads(body) if body else {}
                path = self.path.split("?", 1)[0]
                fake.requests.append({"path": path, "headers": dict(self.headers), "body": parsed})
                if path == "/open-apis/im/v1/messages/om_reply":
                    if fake.fail_put:
                        self._send_json({"code": 230075, "msg": "message edit unavailable"}, status=400)
                        return
                    self._send_json({"code": 0, "data": {"message_id": "om_reply", "msg_type": parsed.get("msg_type")}})
                    return
                self._send_json({"code": 404, "msg": "not found"}, status=404)

            def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
                body = dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return None

        return Handler


class FakeFeishuOnboardServer:
    def __init__(self) -> None:
        self.poll_count = 0
        self.requests: list[dict[str, Any]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeFeishuOnboardServer:
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                fields = dict(item.split("=", 1) for item in body.split("&") if "=" in item)
                action = fields.get("action")
                fake.requests.append({"path": self.path, "fields": fields})
                if self.path != "/oauth/v1/app/registration":
                    self._send_json({"error": "not_found"}, status=404)
                    return
                if action == "init":
                    self._send_json({"supported_auth_methods": ["client_secret"]})
                    return
                if action == "begin":
                    self._send_json(
                        {
                            "device_code": "dc_test",
                            "verification_uri_complete": "https://accounts.feishu.cn/qr/test",
                            "user_code": "ABCD",
                            "interval": 1,
                            "expire_in": 600,
                        }
                    )
                    return
                if action == "poll":
                    fake.poll_count += 1
                    if fake.poll_count == 1:
                        self._send_json({"error": "authorization_pending"})
                    else:
                        self._send_json(
                            {
                                "client_id": "cli_test",
                                "client_secret": "secret_test",
                                "user_info": {"open_id": "ou_owner", "tenant_brand": "feishu"},
                            }
                        )
                    return
                self._send_json({"error": "bad_action"}, status=400)

            def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
                raw = dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args: Any) -> None:
                return None

        return Handler


if __name__ == "__main__":
    unittest.main()
