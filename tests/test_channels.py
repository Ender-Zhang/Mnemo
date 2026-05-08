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

from mnemo.channels import FeishuChannelConfig, build_feishu_server
from mnemo.core.jsonutil import dumps


class FeishuChannelTests(unittest.TestCase):
    def test_install_script_is_parseable_and_documents_feishu(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
        completed = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        content = script.read_text(encoding="utf-8")
        self.assertIn("NousResearch Hermes Agent", content)
        self.assertIn("mnemo channels feishu serve", content)
        self.assertIn("FEISHU_APP_ID", content)

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

                    send_requests = api.requests_for("/open-apis/im/v1/messages")
                    self.assertEqual(len(send_requests), 1)
                    sent = send_requests[0]["body"]
                    self.assertEqual(sent["receive_id"], "oc_chat")
                    self.assertEqual(sent["msg_type"], "text")
                    content = json.loads(sent["content"])
                    self.assertIn("已创建一次 Mnemo 运行", content["text"])

                    status, _, body = server.request("POST", "/feishu/webhook", payload)
                    self.assertEqual(status, 200, body)
                    self.assertEqual(json.loads(body), {"code": 0, "msg": "duplicate"})
                    self.assertTrue(server.service.wait_for_idle(timeout_s=5.0))
                    self.assertEqual(len(api.requests_for("/open-apis/im/v1/messages")), 1)

            session_file = Path(tmp) / "channels" / "feishu_sessions.json"
            sessions = json.loads(session_file.read_text(encoding="utf-8"))
            self.assertTrue(sessions["oc_chat"].startswith("conv_"))

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


if __name__ == "__main__":
    unittest.main()
