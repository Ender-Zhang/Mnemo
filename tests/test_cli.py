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
        self.assertIn("Mnemo personal AI runtime", completed.stdout)

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
            self.assertEqual(prompt["tool_schema"]["count"], prompt["tool_count"])
            self.assertIn("memory_search", prompt["tool_schema"]["names"])
            self.assertNotIn("input_schema", prompt["tool_schema"])

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

    def test_memory_missing_candidate_errors_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            promote = _run_cli(["memory", "promote", "mem_missing", "--state-dir", tmp])
            reject = _run_cli(["memory", "reject", "mem_missing", "--state-dir", tmp])

            self.assertEqual(promote.returncode, 1)
            self.assertIn("mnemo: Memory candidate not found: mem_missing", promote.stderr)
            self.assertNotIn("Traceback", promote.stderr)
            self.assertEqual(reject.returncode, 1)
            self.assertIn("mnemo: Memory candidate not found: mem_missing", reject.stderr)
            self.assertNotIn("Traceback", reject.stderr)

    def test_memory_search_command_includes_associated_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            seed_id = store.upsert_memory_page(
                "preferences: python",
                "User prefers pytest for Python tests",
                confidence=0.91,
            )
            linked_id = store.upsert_memory_page(
                "preferences: reporting",
                "User expects concise failure summaries",
                confidence=0.84,
            )
            store.add_memory_link(seed_id, linked_id, "related", weight=0.8)

            search = _run_cli(["memory", "search", "pytest", "--state-dir", tmp, "--json"])

            self.assertEqual(search.returncode, 0, search.stderr)
            matches = json.loads(search.stdout)["matches"]
            linked = [item for item in matches if item["type"] == "linked_page"]
            self.assertEqual(linked[0]["id"], linked_id)
            self.assertEqual(linked[0]["relation"], "related")

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

            scan = _run_cli(
                ["skills", "scan", "--state-dir", tmp, "--root", str(root), "--json"],
                env_overrides={"HOME": str(Path(tmp) / "home")},
            )
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

    def test_skill_service_errors_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            promote = _run_cli(["skills", "promote", "missing", "--state-dir", tmp])
            eval_run = _run_cli(["skills", "eval", "case_missing", "--state-dir", tmp])
            crystallize = _run_cli(["skills", "crystallize", "run_missing", "draft", "--state-dir", tmp])

            self.assertEqual(promote.returncode, 1)
            self.assertIn("mnemo: Skill not found: missing", promote.stderr)
            self.assertNotIn("Traceback", promote.stderr)
            self.assertEqual(eval_run.returncode, 1)
            self.assertIn("mnemo: Eval case not found: case_missing", eval_run.stderr)
            self.assertNotIn("Traceback", eval_run.stderr)
            self.assertEqual(crystallize.returncode, 1)
            self.assertIn("mnemo: Run not found: run_missing", crystallize.stderr)
            self.assertNotIn("Traceback", crystallize.stderr)

    def test_skills_scan_uses_workspace_mainstream_default_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            state_dir = root / "state"
            skill_dir = workspace / ".claude" / "skills" / "writer"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: claude-writer\ndescription: Write from Claude root\n---\nUse imported skills.",
                encoding="utf-8",
            )

            scan = _run_cli(
                ["skills", "scan", "--state-dir", str(state_dir), "--json"],
                cwd=workspace,
                env_overrides={"HOME": str(root / "home")},
            )

            self.assertEqual(scan.returncode, 0, scan.stderr)
            skills = json.loads(scan.stdout)["skills"]
            scanned = {skill["name"]: skill for skill in skills}
            self.assertIn("claude-writer", scanned)
            self.assertEqual(
                Path(scanned["claude-writer"]["source_root"]).resolve(),
                (workspace / ".claude" / "skills").resolve(),
            )

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

        skill_evolution = _run_cli(["harness", "eval", "skill-evolution", "--json"])
        self.assertEqual(skill_evolution.returncode, 0, skill_evolution.stderr)
        skill_evolution_payload = json.loads(skill_evolution.stdout)
        self.assertTrue(skill_evolution_payload["passed"])
        self.assertEqual(skill_evolution_payload["case_count"], 4)

        suite_list = _run_cli(["harness", "list", "--json"])
        self.assertEqual(suite_list.returncode, 0, suite_list.stderr)
        self.assertIn("memory-safety", json.loads(suite_list.stdout)["suites"])
        self.assertIn("skill-evolution", json.loads(suite_list.stdout)["suites"])

        with tempfile.TemporaryDirectory() as tmp:
            run = _run_cli(["run", "remember: harness cli replay", "--state-dir", tmp, "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)
            run_id = json.loads(run.stdout)["run_id"]

            replay = _run_cli(["harness", "replay", run_id, "--state-dir", tmp, "--json"])
            self.assertEqual(replay.returncode, 0, replay.stderr)
            replay_payload = json.loads(replay.stdout)
            self.assertTrue(replay_payload["completed"])
            self.assertGreater(replay_payload["event_count"], 0)

    def test_tools_command_can_list_installed_generated_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("tools")
            mission_id = store.create_mission(conversation_id, "tools")
            run_id = store.create_run(conversation_id, mission_id, "tools")
            candidate_id = store.add_tool_candidate(
                run_id,
                "lookup_memory",
                {
                    "name": "lookup_memory",
                    "description": "Lookup memory with a focused argument name",
                    "risk": "read",
                    "input_schema": {
                        "type": "object",
                        "properties": {"term": {"type": "string"}},
                        "required": ["term"],
                    },
                    "implementation": {
                        "type": "alias",
                        "target_tool": "memory_search",
                        "argument_map": {"query": {"from": "term"}},
                    },
                },
            )
            store.upsert_generated_tool(
                candidate_id=candidate_id,
                name="lookup_memory",
                description="Lookup memory with a focused argument name",
                risk="read",
                input_schema={
                    "type": "object",
                    "properties": {"term": {"type": "string"}},
                    "required": ["term"],
                },
                implementation={
                    "type": "alias",
                    "target_tool": "memory_search",
                    "argument_map": {"query": {"from": "term"}},
                },
            )

            listed = _run_cli(["tools", "--state-dir", tmp, "--json"])

            self.assertEqual(listed.returncode, 0, listed.stderr)
            tool_names = {tool["name"] for tool in json.loads(listed.stdout)["tools"]}
            self.assertIn("lookup_memory", tool_names)

    def test_tool_evolution_lifecycle_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("tool cli")
            mission_id = store.create_mission(conversation_id, "tool cli")
            run_id = store.create_run(conversation_id, mission_id, "tool cli")
            candidate_id = store.add_tool_candidate(run_id, "lookup_memory", _tool_alias_spec("lookup_memory"))
            case_id = store.add_eval_case(run_id, "lookup_memory smoke", {"tool_candidate": "lookup_memory"})
            store.update_eval_case_status(case_id, "passed", result={"ok": True})

            candidates = _run_cli(["tools", "candidates", "--state-dir", tmp, "--json"])
            review = _run_cli(["tools", "review", candidate_id, "--state-dir", tmp, "--json"])
            install = _run_cli(["tools", "install", candidate_id, "--state-dir", tmp, "--json"])
            listed = _run_cli(["tools", "list", "--state-dir", tmp, "--json"])
            uninstall = _run_cli(["tools", "uninstall", "lookup_memory", "--state-dir", tmp, "--json"])
            listed_after = _run_cli(["tools", "--state-dir", tmp, "--json"])

            self.assertEqual(candidates.returncode, 0, candidates.stderr)
            self.assertIn(candidate_id, {item["id"] for item in json.loads(candidates.stdout)["candidates"]})
            self.assertEqual(review.returncode, 0, review.stderr)
            self.assertEqual(json.loads(review.stdout)["status"], "ready")
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertTrue(json.loads(install.stdout)["installed"])
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("lookup_memory", {tool["name"] for tool in json.loads(listed.stdout)["tools"]})
            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertEqual(json.loads(uninstall.stdout)["status"], "disabled")
            self.assertEqual(listed_after.returncode, 0, listed_after.stderr)
            self.assertNotIn("lookup_memory", {tool["name"] for tool in json.loads(listed_after.stdout)["tools"]})

    def test_tool_evolution_cli_errors_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review = _run_cli(["tools", "review", "tc_missing", "--state-dir", tmp])
            install = _run_cli(["tools", "install", "tc_missing", "--state-dir", tmp])
            uninstall = _run_cli(["tools", "uninstall", "missing_tool", "--state-dir", tmp])

            self.assertEqual(review.returncode, 1)
            self.assertIn("mnemo: tool candidate not found: tc_missing", review.stderr)
            self.assertNotIn("Traceback", review.stderr)
            self.assertEqual(install.returncode, 1)
            self.assertIn("mnemo: tool candidate not found: tc_missing", install.stderr)
            self.assertNotIn("Traceback", install.stderr)
            self.assertEqual(uninstall.returncode, 1)
            self.assertIn("mnemo: generated tool not found: missing_tool", uninstall.stderr)
            self.assertNotIn("Traceback", uninstall.stderr)

    def test_evals_list_and_record_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("eval cli")
            mission_id = store.create_mission(conversation_id, "eval cli")
            run_id = store.create_run(conversation_id, mission_id, "eval cli")
            tool_case_id = store.add_eval_case(
                run_id,
                "lookup_memory smoke",
                {"tool_candidate": "lookup_memory"},
            )
            skill_case_id = store.add_eval_case(
                run_id,
                "writer smoke",
                {"skill_name": "writer"},
            )

            tool_list = _run_cli(["evals", "list", "--tool-name", "lookup_memory", "--state-dir", tmp, "--json"])
            skill_list = _run_cli(["evals", "list", "--skill-name", "writer", "--state-dir", tmp, "--json"])
            record = _run_cli(
                [
                    "evals",
                    "record",
                    tool_case_id,
                    "passed",
                    "--result-json",
                    '{"ok":true,"source":"manual"}',
                    "--state-dir",
                    tmp,
                    "--json",
                ]
            )
            passed_list = _run_cli(["evals", "list", "--status", "passed", "--state-dir", tmp, "--json"])

            self.assertEqual(tool_list.returncode, 0, tool_list.stderr)
            self.assertEqual([case["id"] for case in json.loads(tool_list.stdout)["eval_cases"]], [tool_case_id])
            self.assertEqual(skill_list.returncode, 0, skill_list.stderr)
            self.assertEqual([case["id"] for case in json.loads(skill_list.stdout)["eval_cases"]], [skill_case_id])
            self.assertEqual(record.returncode, 0, record.stderr)
            recorded = json.loads(record.stdout)["eval_case"]
            self.assertEqual(recorded["status"], "passed")
            self.assertEqual(recorded["result"], {"ok": True, "source": "manual"})
            self.assertEqual(json.loads(passed_list.stdout)["eval_cases"][0]["id"], tool_case_id)

    def test_evals_record_errors_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("eval cli")
            mission_id = store.create_mission(conversation_id, "eval cli")
            run_id = store.create_run(conversation_id, mission_id, "eval cli")
            case_id = store.add_eval_case(run_id, "writer smoke", {"skill_name": "writer"})

            missing = _run_cli(["evals", "record", "eval_missing", "passed", "--state-dir", tmp])
            invalid_json = _run_cli(
                ["evals", "record", case_id, "failed", "--result-json", "[1]", "--state-dir", tmp]
            )

            self.assertEqual(missing.returncode, 1)
            self.assertIn("mnemo: eval case not found: eval_missing", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)
            self.assertEqual(invalid_json.returncode, 1)
            self.assertIn("mnemo: --result-json must be a JSON object", invalid_json.stderr)
            self.assertNotIn("Traceback", invalid_json.stderr)

    def test_config_inspect_redacts_api_key(self) -> None:
        config = _run_cli(["config", "inspect", "--api-key", "secret-value", "--json"])

        self.assertEqual(config.returncode, 0, config.stderr)
        payload = json.loads(config.stdout)
        self.assertEqual(payload["api_key"], "***")
        self.assertNotIn("secret-value", config.stdout)

    def test_config_smoke_checks_openai_models_and_chat_without_leaking_key(self) -> None:
        with FakeChatServer(
            {
                "id": "chatcmpl_smoke",
                "model": "fake-model",
                "choices": [{"message": {"content": "Smoke reply"}, "finish_reason": "stop"}],
            },
            models_response={"data": [{"id": "fake-model"}, {"id": "other-model"}]},
        ) as server:
            smoke = _run_cli(
                [
                    "config",
                    "smoke",
                    "--provider",
                    "openai-compatible",
                    "--base-url",
                    server.base_url,
                    "--model",
                    "fake-model",
                    "--api-key",
                    "secret-value",
                    "--json",
                ]
            )

        self.assertEqual(smoke.returncode, 0, smoke.stderr)
        payload = json.loads(smoke.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["models"]["count"], 2)
        self.assertEqual(payload["models"]["ids"][0], "fake-model")
        self.assertEqual(payload["chat"]["response_preview"], "Smoke reply")
        self.assertEqual(payload["config"]["api_key"], "***")
        self.assertNotIn("secret-value", smoke.stdout)
        self.assertEqual([request["path"] for request in server.requests], ["/models", "/chat/completions"])
        self.assertEqual(server.requests[0]["headers"]["Authorization"], "Bearer secret-value")

    def test_config_smoke_checks_anthropic_chat(self) -> None:
        with FakeChatServer(
            {
                "id": "msg_smoke",
                "model": "claude-fake",
                "role": "assistant",
                "content": [{"type": "text", "text": "Anthropic smoke"}],
                "stop_reason": "end_turn",
            }
        ) as server:
            smoke = _run_cli(
                [
                    "config",
                    "smoke",
                    "--provider",
                    "anthropic",
                    "--base-url",
                    server.base_url,
                    "--model",
                    "claude-fake",
                    "--json",
                ]
            )

        self.assertEqual(smoke.returncode, 0, smoke.stderr)
        payload = json.loads(smoke.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["models"]["skipped"])
        self.assertEqual(payload["chat"]["response_preview"], "Anthropic smoke")
        self.assertEqual(server.requests[0]["path"], "/messages")

    def test_config_smoke_returns_nonzero_for_provider_status_error(self) -> None:
        with FakeChatServer({"error": {"message": "unavailable"}}, status=503) as server:
            smoke = _run_cli(
                [
                    "config",
                    "smoke",
                    "--provider",
                    "openai-compatible",
                    "--base-url",
                    server.base_url,
                    "--model",
                    "fake-model",
                    "--json",
                ]
            )

        self.assertEqual(smoke.returncode, 1)
        self.assertIn("provider returned HTTP 503", smoke.stderr)

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

    def test_runs_cancel_and_daemon_cancel_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("cancel")
            mission_id = store.create_mission(conversation_id, "cancel")
            run_id = store.create_run(conversation_id, mission_id, "long work")
            queue_id = store.enqueue_run_request("remember: cancel queued")

            run_cancel = _run_cli(["runs", "cancel", run_id, "--state-dir", tmp, "--reason", "user stop", "--json"])
            queue_cancel = _run_cli(["daemon", "cancel", queue_id, "--state-dir", tmp, "--json"])

            self.assertEqual(run_cancel.returncode, 0, run_cancel.stderr)
            self.assertEqual(queue_cancel.returncode, 0, queue_cancel.stderr)
            run_payload = json.loads(run_cancel.stdout)
            queue_payload = json.loads(queue_cancel.stdout)
            self.assertTrue(run_payload["changed"])
            self.assertEqual(run_payload["status"], "cancelled")
            self.assertTrue(queue_payload["changed"])
            self.assertEqual(queue_payload["status"], "cancelled")
            self.assertEqual(store.get_run(run_id)["status"], "cancelled")
            self.assertEqual(store.list_queue_items(status="cancelled")[0]["id"], queue_id)
            self.assertIn("run.cancel.requested", [event["event_type"] for event in store.get_run_events(run_id)])


def _run_cli(
    args: list[str],
    *,
    cwd: Path | None = None,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "mnemo", *args],
        cwd=cwd or ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _tool_alias_spec(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Lookup memory with a focused argument name",
        "risk": "read",
        "input_schema": {
            "type": "object",
            "properties": {"term": {"type": "string"}},
            "required": ["term"],
            "additionalProperties": False,
        },
        "implementation": {
            "type": "alias",
            "target_tool": "memory_search",
            "argument_map": {"query": {"from": "term"}, "limit": {"const": 5}},
        },
    }


class FakeChatServer:
    def __init__(
        self,
        response: dict[str, Any],
        delay_s: float = 0.0,
        *,
        models_response: dict[str, Any] | None = None,
        status: int = 200,
    ) -> None:
        self.response = response
        self.delay_s = delay_s
        self.models_response = models_response or {"data": []}
        self.status = status
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
            def do_GET(self) -> None:
                fake_server.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": None,
                    }
                )
                self._send_json(fake_server.models_response)

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
                self._send_json(fake_server.response)

            def _send_json(self, payload: dict[str, Any]) -> None:
                response_body = json.dumps(payload).encode("utf-8")
                self.send_response(fake_server.status)
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
