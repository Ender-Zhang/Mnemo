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

from mnemo.storage import StateStore


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
            self.assertEqual(
                [message["role"] for message in server.requests[0]["body"]["messages"]],
                ["system", "system", "system", "system", "user"],
            )

            inspect = _run_cli(["prompt", "inspect", payload["run_id"], "--state-dir", tmp, "--json"])
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            prompt = json.loads(inspect.stdout)["prompt"]
            self.assertEqual(
                prompt["stable_prefix"],
                ["system.identity", "developer.operating_principles", "tools.cards"],
            )
            self.assertEqual(prompt["blocks"][0]["id"], "system.identity")

    def test_run_with_anthropic_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with FakeChatServer(
                {
                    "id": "msg_cli",
                    "model": "claude-fake",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Anthropic reply"}],
                    "stop_reason": "end_turn",
                }
            ) as server:
                run = _run_cli(
                    [
                        "run",
                        "hello anthropic",
                        "--state-dir",
                        tmp,
                        "--provider",
                        "anthropic",
                        "--base-url",
                        server.base_url,
                        "--model",
                        "claude-fake",
                        "--json",
                    ]
                )

            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual(payload["response"], "Anthropic reply")
            self.assertEqual(server.requests[0]["path"], "/messages")
            self.assertEqual(server.requests[0]["body"]["model"], "claude-fake")
            self.assertEqual(server.requests[0]["body"]["messages"][-1]["role"], "user")
            self.assertIn("system", server.requests[0]["body"])

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

    def test_memory_search_and_dream_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _run_cli(["run", "remember: User likes DreamCycle", "--state-dir", tmp, "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)

            search_before = _run_cli(["memory", "search", "DreamCycle", "--state-dir", tmp, "--json"])
            self.assertEqual(search_before.returncode, 0, search_before.stderr)
            before_payload = json.loads(search_before.stdout)
            self.assertEqual(before_payload["matches"][0]["type"], "candidate")

            dream = _run_cli(["dream", "run", "--state-dir", tmp, "--min-confidence", "0.7", "--json"])
            self.assertEqual(dream.returncode, 0, dream.stderr)
            dream_payload = json.loads(dream.stdout)
            self.assertEqual(len(dream_payload["promoted"]), 1)

            search_after = _run_cli(["memory", "search", "DreamCycle", "--state-dir", tmp, "--json"])
            self.assertEqual(search_after.returncode, 0, search_after.stderr)
            after_types = {item["type"] for item in json.loads(search_after.stdout)["matches"]}
            self.assertIn("page", after_types)

    def test_events_chat_and_replay_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _run_cli(["run", "remember: replay CLI", "--state-dir", tmp, "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)
            run_id = json.loads(run.stdout)["run_id"]

            events = _run_cli(["events", run_id, "--state-dir", tmp, "--chat", "--json"])
            self.assertEqual(events.returncode, 0, events.stderr)
            chat_events = json.loads(events.stdout)["events"]
            self.assertEqual(chat_events[0]["type"], "turn.started")
            self.assertEqual(chat_events[-1]["type"], "run.completed")

            replay = _run_cli(["replay", run_id, "--state-dir", tmp, "--json"])
            self.assertEqual(replay.returncode, 0, replay.stderr)
            replay_payload = json.loads(replay.stdout)
            self.assertTrue(replay_payload["completed"])
            self.assertGreater(replay_payload["event_count"], 0)

    def test_skills_scan_view_and_promote_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skill-root"
            skill_dir = root / "writer"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: writer\ndescription: Write concise notes\n---\nUse short notes.",
                encoding="utf-8",
            )

            scan = _run_cli(["skills", "scan", "--state-dir", tmp, "--root", str(root), "--json"])
            self.assertEqual(scan.returncode, 0, scan.stderr)
            self.assertIn("writer", {skill["name"] for skill in json.loads(scan.stdout)["skills"]})

            view = _run_cli(["skills", "view", "writer", "--state-dir", tmp, "--json"])
            self.assertEqual(view.returncode, 0, view.stderr)
            self.assertIn("Use short notes.", json.loads(view.stdout)["skill"]["body"])

            review = _run_cli(["skills", "review", "writer", "--state-dir", tmp, "--json"])
            self.assertEqual(review.returncode, 0, review.stderr)
            self.assertIn(json.loads(review.stdout)["status"], {"ready", "active"})

            store = StateStore(tmp)
            conversation_id = store.create_conversation("skill eval")
            mission_id = store.create_mission(conversation_id, "skill eval")
            run_id = store.create_run(conversation_id, mission_id, "skill eval")
            case_id = store.add_eval_case(
                run_id,
                "writer smoke",
                {"skill_name": "writer", "body_contains": "Use short notes."},
            )
            skill_eval = _run_cli(["skills", "eval", case_id, "--state-dir", tmp, "--json"])
            self.assertEqual(skill_eval.returncode, 0, skill_eval.stderr)
            self.assertEqual(json.loads(skill_eval.stdout)["status"], "passed")

            promote = _run_cli(["skills", "promote", "writer", "--state-dir", tmp, "--json"])
            self.assertEqual(promote.returncode, 0, promote.stderr)
            path = Path(json.loads(promote.stdout)["path"])
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "SKILL.md")

    def test_skills_crystallize_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _run_cli(["run", "artifact: Launch secret body", "--state-dir", tmp, "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)
            run_id = json.loads(run.stdout)["run_id"]

            crystallize = _run_cli(
                [
                    "skills",
                    "crystallize",
                    run_id,
                    "artifact-sop",
                    "--state-dir",
                    tmp,
                    "--description",
                    "Capture artifact workflow",
                    "--json",
                ]
            )
            self.assertEqual(crystallize.returncode, 0, crystallize.stderr)
            payload = json.loads(crystallize.stdout)
            self.assertEqual(payload["status"], "draft")
            self.assertEqual(payload["tool_names"], ["artifact_update"])

            view = _run_cli(["skills", "view", "artifact-sop", "--state-dir", tmp, "--json"])
            self.assertEqual(view.returncode, 0, view.stderr)
            body = json.loads(view.stdout)["skill"]["body"]
            self.assertIn("artifact_update", body)
            self.assertNotIn("Launch secret body", body)

    def test_harness_eval_and_replay_commands(self) -> None:
        eval_run = _run_cli(["harness", "eval", "personalization-core", "--json"])
        self.assertEqual(eval_run.returncode, 0, eval_run.stderr)
        eval_payload = json.loads(eval_run.stdout)
        self.assertTrue(eval_payload["passed"])
        self.assertEqual(eval_payload["case_count"], 3)

        memory_safety = _run_cli(["harness", "eval", "memory-safety", "--json"])
        self.assertEqual(memory_safety.returncode, 0, memory_safety.stderr)
        memory_safety_payload = json.loads(memory_safety.stdout)
        self.assertTrue(memory_safety_payload["passed"])
        self.assertEqual(memory_safety_payload["case_count"], 4)

        suite_list = _run_cli(["harness", "list", "--json"])
        self.assertEqual(suite_list.returncode, 0, suite_list.stderr)
        self.assertIn("memory-safety", json.loads(suite_list.stdout)["suites"])

        with tempfile.TemporaryDirectory() as tmp:
            run = _run_cli(["run", "remember: harness cli replay", "--state-dir", tmp, "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)
            run_id = json.loads(run.stdout)["run_id"]

            replay = _run_cli(["harness", "replay", run_id, "--state-dir", tmp, "--json"])
            self.assertEqual(replay.returncode, 0, replay.stderr)
            replay_payload = json.loads(replay.stdout)
            self.assertTrue(replay_payload["completed"])
            self.assertGreater(replay_payload["event_count"], 0)

    def test_config_inspect_redacts_api_key(self) -> None:
        config = _run_cli(["config", "inspect", "--api-key", "secret-value", "--json"])

        self.assertEqual(config.returncode, 0, config.stderr)
        payload = json.loads(config.stdout)
        self.assertEqual(payload["api_key"], "***")
        self.assertNotIn("secret-value", config.stdout)

    def test_backup_export_and_import_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            archive = root / "mnemo-backup.zip"

            run = _run_cli(["run", "remember: BackupCLI preference", "--state-dir", str(source), "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)

            export = _run_cli(["backup", "export", str(archive), "--state-dir", str(source), "--json"])
            self.assertEqual(export.returncode, 0, export.stderr)
            export_payload = json.loads(export.stdout)
            self.assertTrue(Path(export_payload["archive_path"]).exists())
            self.assertGreaterEqual(export_payload["file_count"], 1)

            imported = _run_cli(["backup", "import", str(archive), "--state-dir", str(target), "--json"])
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertGreaterEqual(json.loads(imported.stdout)["file_count"], 1)

            search = _run_cli(["memory", "search", "BackupCLI", "--state-dir", str(target), "--json"])
            self.assertEqual(search.returncode, 0, search.stderr)
            self.assertTrue(json.loads(search.stdout)["matches"])

    def test_daemon_enqueue_status_run_and_recover_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            enqueue = _run_cli(["daemon", "enqueue", "remember: DaemonCLI preference", "--state-dir", tmp, "--json"])
            self.assertEqual(enqueue.returncode, 0, enqueue.stderr)
            queue_id = json.loads(enqueue.stdout)["queue_id"]

            status = _run_cli(["daemon", "status", "--state-dir", tmp, "--json"])
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)["queue"]["counts"]["pending"], 1)

            run = _run_cli(["daemon", "run", "--state-dir", tmp, "--limit", "1", "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)
            run_payload = json.loads(run.stdout)
            self.assertEqual(run_payload["processed"][0]["id"], queue_id)
            self.assertEqual(run_payload["processed"][0]["status"], "completed")

            search = _run_cli(["memory", "search", "DaemonCLI", "--state-dir", tmp, "--json"])
            self.assertEqual(search.returncode, 0, search.stderr)
            self.assertTrue(json.loads(search.stdout)["matches"])

            store = StateStore(tmp)
            stale_id = store.enqueue_run_request("remember: stale daemon cli")
            store.claim_next_queue_item("stale-worker")
            with store.connect() as conn:
                conn.execute(
                    "UPDATE run_queue SET claimed_at = 0, heartbeat_at = 0 WHERE id = ?",
                    (stale_id,),
                )

            recover = _run_cli(["daemon", "recover", "--state-dir", tmp, "--stale-after-s", "1", "--json"])
            self.assertEqual(recover.returncode, 0, recover.stderr)
            self.assertEqual(json.loads(recover.stdout)["recovered"][0]["id"], stale_id)


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
