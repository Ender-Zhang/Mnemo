from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingTCPServer
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_help_works(self) -> None:
        completed = _run_cli(["--help"])
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Mnemo personal AI runtime foundation", completed.stdout)

    def test_init_and_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            init = _run_cli(["init", "--state-dir", tmp])
            self.assertEqual(init.returncode, 0)
            self.assertTrue((Path(tmp) / "state.db").exists())

            run = _run_cli(["run", "remember: CLI should emit JSON", "--state-dir", tmp, "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)
            self.assertTrue(payload["run_id"].startswith("run_"))
            self.assertEqual(payload["tool_results"][0]["name"], "memory_write_candidate")

    def test_run_stream_outputs_ndjson_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _run_cli(["run", "remember: CLI stream", "--state-dir", tmp, "--stream"])

            self.assertEqual(run.returncode, 0, run.stderr)
            events = [json.loads(line) for line in run.stdout.splitlines()]
            event_types = [event["type"] for event in events]
            self.assertIn("action.queued", event_types)
            self.assertIn("action.completed", event_types)
            self.assertEqual(events[-1]["type"], "run.completed")
            self.assertEqual(events[-1]["data"]["result"]["tool_results"][0]["name"], "memory_write_candidate")

    def test_run_with_openai_compatible_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with FakeChatServer(
                {
                    "choices": [{"message": {"content": "Provider reply"}, "finish_reason": "stop"}],
                }
            ) as server:
                run = _run_cli(
                    [
                        "run",
                        "hello provider",
                        "--state-dir",
                        tmp,
                        "--provider",
                        "openai-compatible",
                        "--base-url",
                        server.base_url,
                        "--model",
                        "fake-model",
                        "--json",
                    ]
                )

            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual(payload["response"], "Provider reply")
            self.assertEqual(server.requests[0]["body"]["model"], "fake-model")

    def test_run_stream_with_provider_timeout_emits_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with FakeChatServer(
                {"choices": [{"message": {"content": "too late"}}]},
                delay_s=0.2,
            ) as server:
                run = _run_cli(
                    [
                        "run",
                        "timeout provider",
                        "--state-dir",
                        tmp,
                        "--provider",
                        "openai-compatible",
                        "--base-url",
                        server.base_url,
                        "--model",
                        "fake-model",
                        "--timeout-s",
                        "0.01",
                        "--stream",
                    ]
                )

            self.assertEqual(run.returncode, 1)
            events = [json.loads(line) for line in run.stdout.splitlines()]
            self.assertEqual(events[-1]["type"], "run.error")
            self.assertIn("timed out", events[-1]["data"]["error"])


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return subprocess.run(
        [sys.executable, "-m", "mnemo", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class FakeChatServer:
    def __init__(self, response: dict[str, Any], delay_s: float = 0.0) -> None:
        self.response = response
        self.delay_s = delay_s
        self.requests: list[dict[str, Any]] = []
        self._server = DaemonThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeChatServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if fake_server.delay_s:
                    import time

                    time.sleep(fake_server.delay_s)
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                fake_server.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": json.loads(raw_body.decode("utf-8")),
                    }
                )
                response_body = json.dumps(fake_server.response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(response_body)
                    self.wfile.flush()
                except BrokenPipeError:
                    pass
                self.close_connection = True

            def log_message(self, format: str, *args: Any) -> None:
                return None

        return Handler


class DaemonThreadingHTTPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False


if __name__ == "__main__":
    unittest.main()
