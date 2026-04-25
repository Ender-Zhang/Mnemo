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

from mnemo.memory import MemoryEngine
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

    def test_run_accepts_prompt_mode_and_persists_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "SOUL.md").write_text("User prefers private CLI context.", encoding="utf-8")

            run = _run_cli(["run", "hello minimal", "--state-dir", tmp, "--prompt-mode", "minimal", "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)

            inspect = _run_cli(["prompt", "inspect", payload["run_id"], "--state-dir", tmp, "--json"])
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            prompt = json.loads(inspect.stdout)["prompt"]
            block_ids = [block["id"] for block in prompt["blocks"]]

            self.assertEqual(prompt["mode"], "minimal")
            self.assertTrue(prompt["execution_allowed"])
            self.assertEqual(prompt["disclosure_boundary"], "minimal_task_context")
            self.assertNotIn("soul.user_contract", block_ids)

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
            roles = [message["role"] for message in server.requests[0]["body"]["messages"]]
            self.assertEqual(roles[0], "system")
            self.assertEqual(roles[-1], "user")
            self.assertGreaterEqual(len(roles), 5)

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
            self.assertEqual(prompt["tool_bundle"]["tool_count"], prompt["tool_count"])
            self.assertTrue(prompt["tool_bundle"]["bundle_id"].startswith("tb_"))
            self.assertNotIn("input_schema", str(prompt["tool_bundle"]))
            self.assertNotIn("input_schema", prompt["tool_schema"])

    def test_run_injects_soul_and_workspace_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            workspace = root / "workspace"
            state_dir.mkdir()
            workspace.mkdir()
            (state_dir / "SOUL.md").write_text("User prefers CLI bootstrap continuity.", encoding="utf-8")
            (workspace / "AGENTS.md").write_text("Workspace bootstrap from CLI cwd.", encoding="utf-8")
            with FakeChatServer(
                {
                    "choices": [{"message": {"content": "Provider reply"}, "finish_reason": "stop"}],
                }
            ) as server:
                run = _run_cli(
                    [
                        "run",
                        "hello bootstrap",
                        "--state-dir",
                        str(state_dir),
                        "--provider",
                        "openai-compatible",
                        "--base-url",
                        server.base_url,
                        "--model",
                        "fake-model",
                        "--json",
                    ],
                    cwd=workspace,
                )

            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)
            prompt_text = "\n".join(message["content"] for message in server.requests[0]["body"]["messages"])
            self.assertIn("User prefers CLI bootstrap continuity.", prompt_text)
            self.assertIn("Workspace bootstrap from CLI cwd.", prompt_text)

            inspect = _run_cli(["prompt", "inspect", payload["run_id"], "--state-dir", str(state_dir), "--json"])
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            prompt = json.loads(inspect.stdout)["prompt"]
            blocks = {block["id"]: block for block in prompt["blocks"]}
            self.assertIn("soul.user_contract", blocks)
            self.assertIn("workspace.bootstrap.agents_md", blocks)
            self.assertEqual(blocks["workspace.bootstrap.agents_md"]["metadata"]["path"], "AGENTS.md")
            self.assertNotIn("Workspace bootstrap from CLI cwd.", inspect.stdout)

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
            self.assertEqual(dream_payload["kind"], "dream_report")
            self.assertEqual(dream_payload["plan"]["decision_owner"], "model")
            self.assertEqual(len(dream_payload["execution"]["result"]["promoted"]), 1)

            status = _run_cli(["dream", "status", "--state-dir", tmp, "--json"])
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["latest"]["id"], dream_payload["id"])

            report = _run_cli(["dream", "report", "--latest", "--state-dir", tmp, "--json"])
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertEqual(json.loads(report.stdout)["id"], dream_payload["id"])

            missing_report = _run_cli(["dream", "report", "missing-report", "--state-dir", tmp, "--json"])
            self.assertEqual(missing_report.returncode, 1)
            self.assertIn("mnemo: dream report not found", missing_report.stderr)

            now = _run_cli(["dream", "--now", "--state-dir", tmp, "--json"])
            self.assertEqual(now.returncode, 0, now.stderr)
            self.assertEqual(json.loads(now.stdout)["kind"], "dream_report")

            search_after = _run_cli(["memory", "search", "DreamCycle", "--state-dir", tmp, "--json"])
            self.assertEqual(search_after.returncode, 0, search_after.stderr)
            after_types = {item["type"] for item in json.loads(search_after.stdout)["matches"]}
            self.assertIn("page", after_types)

    def test_memory_notes_command_lists_open_and_processed_w0_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("memory notes")
            mission_id = store.create_mission(conversation_id, "list W0 notes")
            run_id = store.create_run(conversation_id, mission_id, "note")
            open_id = store.add_working_note(
                mission_id,
                run_id,
                "User wants terse implementation updates",
                metadata={"retention": "memory_candidate", "confidence": 0.8},
            )
            processed_id = store.add_working_note(
                mission_id,
                run_id,
                "Temporary scratchpad context",
                metadata={"retention": "ephemeral"},
            )
            store.update_working_note_status(processed_id, "skipped:ephemeral", result={"reason": "ephemeral"})

            default_notes = _run_cli(["memory", "notes", "--state-dir", tmp, "--json"])
            all_notes = _run_cli(["memory", "notes", "--status", "all", "--state-dir", tmp, "--json"])
            plain = _run_cli(["memory", "notes", "--state-dir", tmp])

            self.assertEqual(default_notes.returncode, 0, default_notes.stderr)
            default_payload = json.loads(default_notes.stdout)
            self.assertEqual([note["id"] for note in default_payload["notes"]], [open_id])
            self.assertEqual(default_payload["notes"][0]["metadata"]["retention"], "memory_candidate")
            self.assertEqual(all_notes.returncode, 0, all_notes.stderr)
            all_payload = json.loads(all_notes.stdout)
            self.assertEqual({note["id"] for note in all_payload["notes"]}, {open_id, processed_id})
            self.assertEqual(store.list_working_notes(status="skipped:ephemeral")[0]["result"], {"reason": "ephemeral"})
            self.assertIn(f"note {open_id} [open] retention=memory_candidate", plain.stdout)
            self.assertIn("User wants terse implementation updates", plain.stdout)
            self.assertNotIn(processed_id, plain.stdout)

    def test_memory_list_command_filters_candidates_and_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("memory list")
            mission_id = store.create_mission(conversation_id, "list memory items")
            run_id = store.create_run(conversation_id, mission_id, "remember list command")
            draft_id = store.add_memory_candidate(
                run_id,
                "Draft memory candidate for listing",
                confidence=0.74,
            )
            promoted_id = store.add_memory_candidate(
                run_id,
                "Promoted memory candidate for listing",
                confidence=0.91,
            )
            store.update_memory_candidate_status(promoted_id, "promoted")
            active_page_id = store.upsert_memory_page(
                "preferences: active memory listing",
                "Active memory page for listing",
                confidence=0.88,
            )
            archived_page_id = store.upsert_memory_page(
                "preferences: archived memory listing",
                "Archived memory page for listing",
                confidence=0.52,
                status="archived",
            )

            default_list = _run_cli(["memory", "list", "--state-dir", tmp, "--json"])
            pages = _run_cli(["memory", "list", "--kind", "page", "--state-dir", tmp, "--json"])
            all_items = _run_cli(
                ["memory", "list", "--kind", "all", "--status", "all", "--state-dir", tmp, "--json"]
            )
            plain = _run_cli(["memory", "list", "--kind", "page", "--state-dir", tmp])

            self.assertEqual(default_list.returncode, 0, default_list.stderr)
            default_payload = json.loads(default_list.stdout)
            self.assertEqual([item["id"] for item in default_payload["candidates"]], [draft_id])
            self.assertEqual(default_payload["pages"], [])
            self.assertEqual(pages.returncode, 0, pages.stderr)
            page_ids = {item["id"] for item in json.loads(pages.stdout)["pages"]}
            self.assertEqual(page_ids, {active_page_id})
            self.assertEqual(all_items.returncode, 0, all_items.stderr)
            all_payload = json.loads(all_items.stdout)
            self.assertEqual({item["id"] for item in all_payload["candidates"]}, {draft_id, promoted_id})
            self.assertEqual({item["id"] for item in all_payload["pages"]}, {active_page_id, archived_page_id})
            self.assertIn(f"page {active_page_id} [active] confidence=0.88", plain.stdout)
            self.assertNotIn(archived_page_id, plain.stdout)

    def test_memory_read_command_reads_candidates_and_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("memory read")
            mission_id = store.create_mission(conversation_id, "read memory items")
            run_id = store.create_run(conversation_id, mission_id, "remember read command")
            candidate_id = store.add_memory_candidate(
                run_id,
                "User prefers compact memory inspection",
                dimension="preference",
                confidence=0.83,
            )
            page_id = store.upsert_memory_page(
                "preferences: memory inspection",
                "User wants direct CLI access to stable memory pages",
                confidence=0.91,
            )

            candidate = _run_cli(["memory", "read", candidate_id, "--state-dir", tmp, "--json"])
            page = _run_cli(["memory", "read", page_id, "--state-dir", tmp, "--json"])
            plain = _run_cli(["memory", "read", page_id, "--state-dir", tmp])
            missing = _run_cli(["memory", "read", "mem_missing", "--state-dir", tmp])

            self.assertEqual(candidate.returncode, 0, candidate.stderr)
            self.assertEqual(json.loads(candidate.stdout)["memory"]["type"], "candidate")
            self.assertEqual(json.loads(candidate.stdout)["memory"]["id"], candidate_id)
            self.assertEqual(page.returncode, 0, page.stderr)
            self.assertEqual(json.loads(page.stdout)["memory"]["type"], "page")
            self.assertEqual(json.loads(page.stdout)["memory"]["id"], page_id)
            self.assertIn(f"page {page_id} [active] confidence=0.91", plain.stdout)
            self.assertIn("User wants direct CLI access to stable memory pages", plain.stdout)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("mnemo: memory not found: mem_missing", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)

    def test_memory_health_and_tombstone_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            page_id = store.upsert_memory_page(
                "preferences: old cli",
                "User prefers an old CLI behavior",
                confidence=0.4,
            )

            health_before = _run_cli(["memory", "health", "--state-dir", tmp, "--json"])
            tombstone = _run_cli(
                [
                    "memory",
                    "tombstone",
                    page_id,
                    "--reason",
                    "superseded",
                    "--target-type",
                    "page",
                    "--state-dir",
                    tmp,
                    "--json",
                ]
            )
            tombstones = _run_cli(["memory", "tombstones", "--target-id", page_id, "--state-dir", tmp, "--json"])
            health_plain = _run_cli(["memory", "health", "--state-dir", tmp])
            tombstones_plain = _run_cli(["memory", "tombstones", "--target-id", page_id, "--state-dir", tmp])
            missing = _run_cli(
                ["memory", "tombstone", "mem_missing", "--reason", "rejected", "--state-dir", tmp]
            )

            self.assertEqual(health_before.returncode, 0, health_before.stderr)
            self.assertEqual(json.loads(health_before.stdout)["kind"], "memory_health_report")
            self.assertEqual(tombstone.returncode, 0, tombstone.stderr)
            tombstone_payload = json.loads(tombstone.stdout)
            self.assertEqual(tombstone_payload["target_type"], "page")
            self.assertEqual(tombstone_payload["status"], "tombstoned:superseded")
            self.assertEqual(store.get_memory_page(page_id)["status"], "tombstoned:superseded")
            self.assertEqual(tombstones.returncode, 0, tombstones.stderr)
            listed = json.loads(tombstones.stdout)["tombstones"]
            self.assertEqual(listed[0]["target_id"], page_id)
            self.assertEqual(listed[0]["reason"], "superseded")
            self.assertIn("Memory health overall=", health_plain.stdout)
            self.assertIn(f"tombstone {listed[0]['id']} page:{page_id}", tombstones_plain.stdout)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("mnemo: Memory item not found for tombstone: mem_missing", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)

    def test_memory_links_command_reads_outgoing_and_incoming_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            seed_id = store.upsert_memory_page(
                "preferences: python",
                "User prefers pytest for Python tests",
                confidence=0.9,
            )
            outgoing_id = store.upsert_memory_page(
                "preferences: reporting",
                "User expects concise failure summaries",
                confidence=0.82,
            )
            incoming_id = store.upsert_memory_page(
                "preferences: ci",
                "User expects CI examples",
                confidence=0.78,
            )
            outgoing_link_id = store.add_memory_link(seed_id, outgoing_id, "related", weight=0.8)
            incoming_link_id = store.add_memory_link(incoming_id, seed_id, "supports", weight=0.7)

            both = _run_cli(["memory", "links", seed_id, "--state-dir", tmp, "--json"])
            outgoing = _run_cli(
                ["memory", "links", seed_id, "--direction", "outgoing", "--state-dir", tmp, "--json"]
            )
            incoming = _run_cli(
                ["memory", "links", seed_id, "--direction", "incoming", "--state-dir", tmp, "--json"]
            )
            plain = _run_cli(["memory", "links", seed_id, "--state-dir", tmp])

            self.assertEqual(both.returncode, 0, both.stderr)
            both_payload = json.loads(both.stdout)
            self.assertEqual([link["id"] for link in both_payload["outgoing"]], [outgoing_link_id])
            self.assertEqual([link["id"] for link in both_payload["incoming"]], [incoming_link_id])
            self.assertEqual(outgoing.returncode, 0, outgoing.stderr)
            self.assertEqual(json.loads(outgoing.stdout)["incoming"], [])
            self.assertEqual(incoming.returncode, 0, incoming.stderr)
            self.assertEqual(json.loads(incoming.stdout)["outgoing"], [])
            self.assertIn(f"outgoing {outgoing_link_id} {seed_id} -> {outgoing_id} related weight=0.80", plain.stdout)
            self.assertIn(f"incoming {incoming_link_id} {incoming_id} -> {seed_id} supports weight=0.70", plain.stdout)

    def test_memory_snapshot_command_reads_compiled_l1_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = _run_cli(["memory", "snapshot", "--state-dir", tmp, "--json"])
            self.assertEqual(missing.returncode, 0, missing.stderr)
            self.assertFalse(json.loads(missing.stdout)["exists"])

            store = StateStore(tmp)
            store.initialize()
            snapshot_path = Path(tmp) / "wiki" / "l1-memory-snapshot.json"
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text("{", encoding="utf-8")
            invalid = _run_cli(["memory", "snapshot", "--state-dir", tmp, "--json"])
            self.assertEqual(invalid.returncode, 0, invalid.stderr)
            self.assertFalse(json.loads(invalid.stdout)["exists"])

            page_id = store.upsert_memory_page(
                "preferences: update style",
                "User prefers direct updates " + ("with compact status notes " * 20),
                confidence=0.91,
            )
            store.upsert_memory_page(
                "archived: stale",
                "This full archived page body should not appear",
                status="archived",
            )
            MemoryEngine(store).compile_l1_snapshot(limit=10)

            snapshot = _run_cli(["memory", "snapshot", "--state-dir", tmp, "--json"])
            plain = _run_cli(["memory", "snapshot", "--state-dir", tmp])

            self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
            payload = json.loads(snapshot.stdout)
            self.assertTrue(payload["exists"])
            self.assertEqual(payload["snapshot"]["page_count"], 1)
            self.assertEqual(payload["snapshot"]["items"][0]["id"], page_id)
            self.assertNotIn("content", payload["snapshot"]["items"][0])
            self.assertNotIn("This full archived page body should not appear", snapshot.stdout)
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertIn("L1 memory snapshot page_count=1", plain.stdout)
            self.assertIn(page_id, plain.stdout)

    def test_artifacts_commands_list_and_read_stored_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("artifacts")
            mission_id = store.create_mission(conversation_id, "artifact mission")
            run_id = store.create_run(conversation_id, mission_id, "artifact command")
            other_mission_id = store.create_mission(conversation_id, "other artifact mission")
            other_run_id = store.create_run(conversation_id, other_mission_id, "other artifact command")
            artifact_id = store.upsert_artifact(
                mission_id,
                run_id,
                "Launch Brief",
                "Launch secret body",
                "markdown",
            )
            other_artifact_id = store.upsert_artifact(
                other_mission_id,
                other_run_id,
                "Other Brief",
                "Other secret body",
                "markdown",
            )

            listed = _run_cli(["artifacts", "list", "--state-dir", tmp, "--json"])
            mission_filtered = _run_cli(
                ["artifacts", "list", "--mission-id", mission_id, "--state-dir", tmp, "--json"]
            )
            run_filtered = _run_cli(
                ["artifacts", "list", "--run-id", run_id, "--state-dir", tmp, "--json"]
            )
            read = _run_cli(["artifacts", "read", artifact_id, "--state-dir", tmp, "--json"])
            plain_list = _run_cli(["artifacts", "list", "--state-dir", tmp])
            plain_read = _run_cli(["artifacts", "read", artifact_id, "--state-dir", tmp])
            missing = _run_cli(["artifacts", "read", "art_missing", "--state-dir", tmp])
            no_subcommand = _run_cli(["artifacts"])

            self.assertEqual(listed.returncode, 0, listed.stderr)
            listed_payload = json.loads(listed.stdout)
            self.assertEqual({item["id"] for item in listed_payload["artifacts"]}, {artifact_id, other_artifact_id})
            self.assertNotIn("body", listed.stdout)
            self.assertNotIn("Launch secret body", listed.stdout)
            self.assertEqual(mission_filtered.returncode, 0, mission_filtered.stderr)
            self.assertEqual(json.loads(mission_filtered.stdout)["artifacts"][0]["id"], artifact_id)
            self.assertEqual(run_filtered.returncode, 0, run_filtered.stderr)
            self.assertEqual(json.loads(run_filtered.stdout)["artifacts"][0]["id"], artifact_id)
            self.assertEqual(read.returncode, 0, read.stderr)
            self.assertEqual(json.loads(read.stdout)["artifact"]["body"], "Launch secret body")
            self.assertIn(f"artifact {artifact_id} [markdown]", plain_list.stdout)
            self.assertNotIn("Launch secret body", plain_list.stdout)
            self.assertIn("# Launch Brief", plain_read.stdout)
            self.assertIn("Launch secret body", plain_read.stdout)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("mnemo: artifact not found: art_missing", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)
            self.assertEqual(no_subcommand.returncode, 1)
            self.assertIn("mnemo: artifacts command requires a subcommand", no_subcommand.stderr)
            self.assertNotIn("Traceback", no_subcommand.stderr)

    def test_inbox_commands_list_show_and_resolve_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("inbox cli")
            mission_id = store.create_mission(conversation_id, "inbox cli")
            run_id = store.create_run(conversation_id, mission_id, "ask")
            item_id = store.add_inbox_item(
                category="decision",
                title="Approve CLI decision?",
                priority=1,
                body="Needs confirmation.",
                action_type="choose",
                action_data={"options": ["accepted", "rejected", "ignored"]},
                source_run_id=run_id,
            )
            low_id = store.add_inbox_item(
                category="memory",
                title="Low priority note",
                priority=3,
            )

            listed = _run_cli(["inbox", "--priority", "high", "--state-dir", tmp, "--json"])
            shown = _run_cli(["inbox", "show", item_id, "--state-dir", tmp, "--json"])
            plain = _run_cli(["inbox", "--state-dir", tmp])
            resolved = _run_cli(["inbox", "resolve", item_id, "--accept", "--notes", "approved", "--state-dir", tmp, "--json"])
            resolved_list = _run_cli(["inbox", "--status", "resolved", "--state-dir", tmp, "--json"])
            missing = _run_cli(["inbox", "show", "inbox_missing", "--state-dir", tmp])

            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual([item["id"] for item in json.loads(listed.stdout)["items"]], [item_id])
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(json.loads(shown.stdout)["item"]["action_data"]["options"][0], "accepted")
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertIn(f"inbox {item_id} [open] priority=high category=decision", plain.stdout)
            self.assertIn(low_id, plain.stdout)
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            resolved_item = json.loads(resolved.stdout)["item"]
            self.assertTrue(resolved_item["changed"])
            self.assertEqual(resolved_item["resolution"], "accepted")
            self.assertEqual(resolved_item["resolution_notes"], "approved")
            self.assertEqual([item["id"] for item in json.loads(resolved_list.stdout)["items"]], [item_id])
            self.assertEqual(missing.returncode, 1)
            self.assertIn("mnemo: inbox item not found: inbox_missing", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)

    def test_inbox_resolve_executes_accepted_tool_approval_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("tool approval cli")
            mission_id = store.create_mission(conversation_id, "tool approval cli")
            run_id = store.create_run(conversation_id, mission_id, "open browser")

            def add_approval(call_id: str) -> str:
                return store.add_inbox_item(
                    category="decision",
                    title="Approve browser_open?",
                    priority=1,
                    body="tool risk is not allowed: external",
                    action_type="tool_approval",
                    action_data={
                        "source": "tool_policy",
                        "tool_call": {
                            "call_id": call_id,
                            "provider": "fake",
                            "tool_name": "browser_open",
                            "risk": "external",
                            "arguments": {"url": "https://example.com", "dry_run": True},
                        },
                    },
                    source_run_id=run_id,
                )

            json_item_id = add_approval("call_browser_json")
            plain_item_id = add_approval("call_browser_plain")

            accepted = _run_cli(["inbox", "resolve", json_item_id, "--accept", "--state-dir", tmp, "--json"])
            repeated = _run_cli(["inbox", "resolve", json_item_id, "--accept", "--state-dir", tmp, "--json"])
            plain = _run_cli(["inbox", "resolve", plain_item_id, "--accept", "--state-dir", tmp])

            accepted_payload = json.loads(accepted.stdout)
            repeated_payload = json.loads(repeated.stdout)
            run_event_types = [event["event_type"] for event in store.get_run_events(run_id)]
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(accepted_payload["tool_result"]["tool"], "browser_open")
            self.assertTrue(accepted_payload["tool_result"]["ok"])
            self.assertIn("Browser prepared", accepted_payload["tool_result"]["summary"])
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertFalse(repeated_payload["item"]["changed"])
            self.assertNotIn("tool_result", repeated_payload)
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertIn("tool_result browser_open ok=True: Browser prepared", plain.stdout)
            self.assertEqual(run_event_types.count("tool.approval.executed"), 2)

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

    def test_memory_search_debug_query_includes_query_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            store.upsert_memory_page(
                "preferences: python",
                "User likes pytest assertions",
                confidence=0.91,
            )

            search = _run_cli(
                [
                    "memory",
                    "search",
                    "testing",
                    "preference",
                    "--debug-query",
                    "--state-dir",
                    tmp,
                    "--json",
                ]
            )
            plain = _run_cli(
                [
                    "memory",
                    "search",
                    "testing",
                    "preference",
                    "--debug-query",
                    "--state-dir",
                    tmp,
                ]
            )
            default_search = _run_cli(
                ["memory", "search", "testing", "preference", "--state-dir", tmp, "--json"]
            )

            self.assertEqual(search.returncode, 0, search.stderr)
            payload = json.loads(search.stdout)
            self.assertEqual(payload["query_plan"]["dimensions"], ["preferences"])
            self.assertIn("dimension", payload["matches"][0]["annotations"]["matched_routes"])
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertIn("query_plan routes=", plain.stdout)
            self.assertNotIn("query_plan", json.loads(default_search.stdout))

    def test_memory_search_command_can_search_session_snippets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("session cli")
            mission_id = store.create_mission(conversation_id, "search session messages")
            run_id = store.create_run(conversation_id, mission_id, "Use incident reports with timeline first.")
            store.complete_run(run_id, "I will put timeline first in incident reports.")

            search = _run_cli(["memory", "search", "timeline first", "--scope", "sessions", "--state-dir", tmp, "--json"])
            plain = _run_cli(["memory", "search", "timeline first", "--scope", "sessions", "--state-dir", tmp])

            self.assertEqual(search.returncode, 0, search.stderr)
            matches = json.loads(search.stdout)["matches"]
            self.assertEqual({item["type"] for item in matches}, {"session_message"})
            self.assertEqual({item["conversation_id"] for item in matches}, {conversation_id})
            self.assertEqual({item["mission_id"] for item in matches}, {mission_id})
            self.assertEqual({item["run_id"] for item in matches}, {run_id})
            self.assertNotIn("content", search.stdout)
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertIn("session_message", plain.stdout)
            self.assertIn("timeline first", plain.stdout)

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

            missing_events = _run_cli(["events", "run_missing", "--state-dir", tmp, "--json"])
            missing_replay = _run_cli(["replay", "run_missing", "--state-dir", tmp, "--json"])
            self.assertEqual(missing_events.returncode, 1)
            self.assertIn("mnemo: run not found: run_missing", missing_events.stderr)
            self.assertNotIn("Traceback", missing_events.stderr)
            self.assertEqual(missing_replay.returncode, 1)
            self.assertIn("mnemo: run not found: run_missing", missing_replay.stderr)
            self.assertNotIn("Traceback", missing_replay.stderr)

    def test_runs_list_and_show_commands_inspect_run_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("runs cli")
            mission_id = store.create_mission(conversation_id, "runs cli mission")
            other_mission_id = store.create_mission(conversation_id, "other runs cli mission")
            long_input = "Summarize " + ("important launch context " * 12)
            long_output = "Done " + ("detailed private output " * 12)
            completed_id = store.create_run(conversation_id, mission_id, long_input)
            running_id = store.create_run(conversation_id, other_mission_id, "still running")
            store.complete_run(completed_id, long_output)

            listed = _run_cli(["runs", "list", "--state-dir", tmp, "--json"])
            status_filtered = _run_cli(["runs", "list", "--status", "running", "--state-dir", tmp, "--json"])
            mission_filtered = _run_cli(["runs", "list", "--mission-id", mission_id, "--state-dir", tmp, "--json"])
            conversation_filtered = _run_cli(
                ["runs", "list", "--conversation-id", conversation_id, "--state-dir", tmp, "--json"]
            )
            shown = _run_cli(["runs", "show", completed_id, "--state-dir", tmp, "--json"])
            plain_list = _run_cli(["runs", "list", "--state-dir", tmp])
            plain_show = _run_cli(["runs", "show", completed_id, "--state-dir", tmp])
            missing = _run_cli(["runs", "show", "run_missing", "--state-dir", tmp])
            no_subcommand = _run_cli(["runs"])

            self.assertEqual(listed.returncode, 0, listed.stderr)
            listed_payload = json.loads(listed.stdout)
            self.assertEqual({item["id"] for item in listed_payload["runs"]}, {completed_id, running_id})
            self.assertNotIn("input_text", listed.stdout)
            self.assertNotIn("output_text", listed.stdout)
            self.assertNotIn("detailed private output", listed.stdout)
            self.assertEqual(status_filtered.returncode, 0, status_filtered.stderr)
            self.assertEqual(json.loads(status_filtered.stdout)["runs"][0]["id"], running_id)
            self.assertEqual(mission_filtered.returncode, 0, mission_filtered.stderr)
            self.assertEqual(json.loads(mission_filtered.stdout)["runs"][0]["id"], completed_id)
            self.assertEqual(conversation_filtered.returncode, 0, conversation_filtered.stderr)
            self.assertEqual({item["id"] for item in json.loads(conversation_filtered.stdout)["runs"]}, {completed_id, running_id})
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(json.loads(shown.stdout)["run"]["input_text"], long_input)
            self.assertEqual(json.loads(shown.stdout)["run"]["output_text"], long_output)
            self.assertIn(f"run {completed_id} [completed]", plain_list.stdout)
            self.assertNotIn("detailed private output", plain_list.stdout)
            self.assertIn(long_input, plain_show.stdout)
            self.assertIn(long_output, plain_show.stdout)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("mnemo: run not found: run_missing", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)
            self.assertEqual(no_subcommand.returncode, 1)
            self.assertIn("mnemo: runs command requires a subcommand", no_subcommand.stderr)
            self.assertNotIn("Traceback", no_subcommand.stderr)

    def test_conversations_and_missions_commands_inspect_continuity_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("Primary continuity")
            other_conversation_id = store.create_conversation("Archived continuity")
            mission_id = store.create_mission(conversation_id, "Continue launch planning")
            other_mission_id = store.create_mission(other_conversation_id, "Old planning")
            store.update_mission_checkpoint(mission_id, {"recent_summary": "private checkpoint"})
            with store.connect() as conn:
                conn.execute("UPDATE missions SET status = ? WHERE id = ?", ("completed", other_mission_id))

            conversations = _run_cli(["conversations", "list", "--state-dir", tmp, "--json"])
            conversation = _run_cli(["conversations", "show", conversation_id, "--state-dir", tmp, "--json"])
            plain_conversations = _run_cli(["conversations", "list", "--state-dir", tmp])
            missing_conversation = _run_cli(["conversations", "show", "conv_missing", "--state-dir", tmp])
            no_conversation_subcommand = _run_cli(["conversations"])
            missions = _run_cli(["missions", "list", "--state-dir", tmp, "--json"])
            mission_by_conversation = _run_cli(
                ["missions", "list", "--conversation-id", conversation_id, "--state-dir", tmp, "--json"]
            )
            mission_by_status = _run_cli(["missions", "list", "--status", "completed", "--state-dir", tmp, "--json"])
            mission = _run_cli(["missions", "show", mission_id, "--state-dir", tmp, "--json"])
            plain_missions = _run_cli(["missions", "list", "--state-dir", tmp])
            plain_mission = _run_cli(["missions", "show", mission_id, "--state-dir", tmp])
            missing_mission = _run_cli(["missions", "show", "mis_missing", "--state-dir", tmp])
            no_mission_subcommand = _run_cli(["missions"])

            self.assertEqual(conversations.returncode, 0, conversations.stderr)
            self.assertEqual(
                {item["id"] for item in json.loads(conversations.stdout)["conversations"]},
                {conversation_id, other_conversation_id},
            )
            self.assertEqual(conversation.returncode, 0, conversation.stderr)
            self.assertEqual(json.loads(conversation.stdout)["conversation"]["title"], "Primary continuity")
            self.assertIn(f"conversation {conversation_id}", plain_conversations.stdout)
            self.assertEqual(missing_conversation.returncode, 1)
            self.assertIn("mnemo: conversation not found: conv_missing", missing_conversation.stderr)
            self.assertNotIn("Traceback", missing_conversation.stderr)
            self.assertEqual(no_conversation_subcommand.returncode, 1)
            self.assertIn("mnemo: conversations command requires a subcommand", no_conversation_subcommand.stderr)
            self.assertEqual(missions.returncode, 0, missions.stderr)
            self.assertEqual({item["id"] for item in json.loads(missions.stdout)["missions"]}, {mission_id, other_mission_id})
            self.assertNotIn("private checkpoint", missions.stdout)
            self.assertEqual(json.loads(mission_by_conversation.stdout)["missions"][0]["id"], mission_id)
            self.assertEqual(json.loads(mission_by_status.stdout)["missions"][0]["id"], other_mission_id)
            self.assertEqual(mission.returncode, 0, mission.stderr)
            self.assertEqual(json.loads(mission.stdout)["mission"]["checkpoint"], {"recent_summary": "private checkpoint"})
            self.assertIn(f"mission {mission_id} [active]", plain_missions.stdout)
            self.assertNotIn("private checkpoint", plain_missions.stdout)
            self.assertIn("private checkpoint", plain_mission.stdout)
            self.assertEqual(missing_mission.returncode, 1)
            self.assertIn("mnemo: mission not found: mis_missing", missing_mission.stderr)
            self.assertNotIn("Traceback", missing_mission.stderr)
            self.assertEqual(no_mission_subcommand.returncode, 1)
            self.assertIn("mnemo: missions command requires a subcommand", no_mission_subcommand.stderr)

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

    def test_skills_usage_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("skill usage")
            mission_id = store.create_mission(conversation_id, "skill usage")
            run_id = store.create_run(conversation_id, mission_id, "skill usage")
            store.upsert_skill("writer", "Write concise notes", "Use short notes.", status="active")
            store.record_skill_usage(run_id, "writer", "viewed", evidence=[{"kind": "skill_view"}])
            store.record_skill_usage(
                run_id,
                "writer",
                "outcome",
                outcome="success",
                score=0.75,
                evidence=[{"kind": "manual"}],
            )
            store.record_skill_usage(run_id, "planner", "outcome", outcome="failure", score=-0.25)

            filtered = _run_cli(["skills", "usage", "writer", "--state-dir", tmp, "--json"])
            all_usage = _run_cli(["skills", "usage", "--state-dir", tmp, "--limit", "2", "--json"])
            text = _run_cli(["skills", "usage", "writer", "--state-dir", tmp])

            self.assertEqual(filtered.returncode, 0, filtered.stderr)
            payload = json.loads(filtered.stdout)
            self.assertEqual([event["event_type"] for event in payload["usage"]], ["outcome", "viewed"])
            self.assertEqual(payload["stats"]["writer"]["views"], 1)
            self.assertEqual(payload["stats"]["writer"]["successes"], 1)
            self.assertEqual(payload["stats"]["writer"]["avg_score"], 0.75)
            self.assertEqual(all_usage.returncode, 0, all_usage.stderr)
            self.assertEqual(len(json.loads(all_usage.stdout)["usage"]), 2)
            self.assertEqual(text.returncode, 0, text.stderr)
            self.assertIn("writer outcome outcome=success score=0.75", text.stdout)

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
        self.assertEqual(eval_payload["case_count"], 4)

        memory_safety = _run_cli(["harness", "eval", "memory-safety", "--json"])
        self.assertEqual(memory_safety.returncode, 0, memory_safety.stderr)
        memory_safety_payload = json.loads(memory_safety.stdout)
        self.assertTrue(memory_safety_payload["passed"])
        self.assertEqual(memory_safety_payload["case_count"], 5)

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
            missing_replay = _run_cli(["harness", "replay", "run_missing", "--state-dir", tmp, "--json"])
            self.assertEqual(missing_replay.returncode, 1)
            self.assertIn("mnemo: run not found: run_missing", missing_replay.stderr)
            self.assertNotIn("Traceback", missing_replay.stderr)

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

    def test_evals_create_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("eval cli")
            mission_id = store.create_mission(conversation_id, "eval cli")
            run_id = store.create_run(conversation_id, mission_id, "eval cli")

            create = _run_cli(
                [
                    "evals",
                    "create",
                    run_id,
                    "lookup_memory smoke",
                    "--case-json",
                    '{"tool_candidate":"lookup_memory"}',
                    "--state-dir",
                    tmp,
                    "--json",
                ]
            )
            payload = json.loads(create.stdout)
            case_id = payload["eval_case"]["id"]
            record = _run_cli(["evals", "record", case_id, "passed", "--state-dir", tmp, "--json"])
            listed = _run_cli(["evals", "list", "--tool-name", "lookup_memory", "--state-dir", tmp, "--json"])

            self.assertEqual(create.returncode, 0, create.stderr)
            self.assertEqual(payload["eval_case"]["status"], "draft")
            self.assertEqual(payload["eval_case"]["case"], {"tool_candidate": "lookup_memory"})
            self.assertEqual(record.returncode, 0, record.stderr)
            self.assertEqual(json.loads(record.stdout)["eval_case"]["status"], "passed")
            self.assertEqual([case["id"] for case in json.loads(listed.stdout)["eval_cases"]], [case_id])

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
            missing_run = _run_cli(
                [
                    "evals",
                    "create",
                    "run_missing",
                    "lookup_memory smoke",
                    "--case-json",
                    '{"tool_candidate":"lookup_memory"}',
                    "--state-dir",
                    tmp,
                ]
            )
            invalid_case_json = _run_cli(
                ["evals", "create", run_id, "writer smoke", "--case-json", "[]", "--state-dir", tmp]
            )

            self.assertEqual(missing.returncode, 1)
            self.assertIn("mnemo: eval case not found: eval_missing", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)
            self.assertEqual(invalid_json.returncode, 1)
            self.assertIn("mnemo: --result-json must be a JSON object", invalid_json.stderr)
            self.assertNotIn("Traceback", invalid_json.stderr)
            self.assertEqual(missing_run.returncode, 1)
            self.assertIn("mnemo: run not found: run_missing", missing_run.stderr)
            self.assertNotIn("Traceback", missing_run.stderr)
            self.assertEqual(invalid_case_json.returncode, 1)
            self.assertIn("mnemo: --case-json must be a JSON object", invalid_case_json.stderr)
            self.assertNotIn("Traceback", invalid_case_json.stderr)

    def test_config_inspect_redacts_api_key(self) -> None:
        config = _run_cli(["config", "inspect", "--api-key", "secret-value", "--json"])

        self.assertEqual(config.returncode, 0, config.stderr)
        payload = json.loads(config.stdout)
        self.assertEqual(payload["api_key"], "***")
        self.assertNotIn("secret-value", config.stdout)

    def test_config_capabilities_reports_provider_registry_without_leaking_key(self) -> None:
        config = _run_cli(
            [
                "config",
                "capabilities",
                "--provider",
                "openai-compatible",
                "--model",
                "fake-model",
                "--api-key",
                "secret-value",
                "--json",
            ]
        )

        self.assertEqual(config.returncode, 0, config.stderr)
        payload = json.loads(config.stdout)
        self.assertEqual(payload["capabilities"]["adapter_version"], "openai.v1")
        self.assertEqual(payload["capabilities"]["prompt_cache_strategy"], "automatic_prefix")
        self.assertEqual(payload["cache_plan"]["strategy"], "automatic_prefix")
        self.assertEqual(payload["config"]["api_key"], "***")
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
        self.assertEqual(payload["capabilities"]["adapter_version"], "openai.v1")
        self.assertEqual(payload["cache_plan"]["strategy"], "automatic_prefix")
        self.assertEqual(payload["config"]["api_key"], "***")
        self.assertNotIn("secret-value", smoke.stdout)
        self.assertEqual([request["path"] for request in server.requests], ["/models", "/chat/completions"])
        self.assertEqual(server.requests[0]["headers"]["Authorization"], "Bearer secret-value")

    def test_config_smoke_can_probe_openai_streaming_chat(self) -> None:
        with FakeChatServer(
            {"unused": True},
            models_response={"data": [{"id": "fake-stream-model"}]},
            stream_chunks=[
                {
                    "id": "chatcmpl_stream",
                    "choices": [{"delta": {"content": "Stream "}, "finish_reason": None}],
                },
                {
                    "id": "chatcmpl_stream",
                    "choices": [{"delta": {"content": "reply"}, "finish_reason": "stop"}],
                },
            ],
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
                    "fake-stream-model",
                    "--stream",
                    "--json",
                ]
            )

        self.assertEqual(smoke.returncode, 0, smoke.stderr)
        payload = json.loads(smoke.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["chat"]["response_preview"], "Stream reply")
        self.assertEqual(server.requests[1]["body"]["stream"], True)

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

    def test_api_schema_command_exposes_core_contract(self) -> None:
        json_result = _run_cli(["api", "schema", "--json"])
        text_result = _run_cli(["api", "schema"])

        self.assertEqual(json_result.returncode, 0, json_result.stderr)
        payload = json.loads(json_result.stdout)["api_schema"]
        self.assertEqual(payload["schema_version"], "mnemo.core_api.v1")
        self.assertEqual(set(payload["methods"]), {"context", "recall", "run", "replay", "evaluate"})
        self.assertNotIn("input_schema", str(payload["methods"]["run"]["output_schema"]))
        self.assertEqual(text_result.returncode, 0, text_result.stderr)
        self.assertIn("MnemoCore mnemo.core_api.v1", text_result.stdout)
        self.assertIn("- context:", text_result.stdout)

    def test_mcp_tools_and_call_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = _run_cli(["mcp", "tools", "--state-dir", tmp, "--json"])
            call = _run_cli(
                [
                    "mcp",
                    "call",
                    "mnemo_context",
                    "--state-dir",
                    tmp,
                    "--arguments-json",
                    '{"intent":"CLI MCP"}',
                    "--json",
                ]
            )
            invalid = _run_cli(
                [
                    "mcp",
                    "call",
                    "mnemo_context",
                    "--state-dir",
                    tmp,
                    "--arguments-json",
                    "{",
                ]
            )

            self.assertEqual(tools.returncode, 0, tools.stderr)
            self.assertIn("mnemo_context", {tool["name"] for tool in json.loads(tools.stdout)["tools"]})
            self.assertEqual(call.returncode, 0, call.stderr)
            self.assertEqual(json.loads(call.stdout)["result"]["kind"], "context_block")
            self.assertEqual(invalid.returncode, 1)
            self.assertIn("mnemo: invalid --arguments-json", invalid.stderr)
            self.assertNotIn("Traceback", invalid.stderr)

    def test_mcp_serve_transports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            content_length = _run_cli(
                ["mcp", "serve", "--state-dir", tmp],
                input_text=_mcp_text_frame({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
            )
            jsonl = _run_cli(
                ["mcp", "serve", "--transport", "jsonl", "--state-dir", tmp],
                input_text=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n",
            )

            self.assertEqual(content_length.returncode, 0, content_length.stderr)
            content_length_frames = _read_mcp_text_frames(content_length.stdout)
            self.assertEqual(content_length_frames[0]["id"], 1)
            self.assertIn("tools", content_length_frames[0]["result"])

            self.assertEqual(jsonl.returncode, 0, jsonl.stderr)
            jsonl_response = json.loads(jsonl.stdout)
            self.assertEqual(jsonl_response["id"], 2)
            self.assertIn("tools", jsonl_response["result"])

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

    def test_schedule_add_list_tick_and_status_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            add = _run_cli(
                [
                    "schedule",
                    "add",
                    "--kind",
                    "cron",
                    "--title",
                    "Scheduled CLI",
                    "--message",
                    "remember: ScheduledCLI preference",
                    "--schedule",
                    "once",
                    "--next-run-at",
                    "0",
                    "--state-dir",
                    tmp,
                    "--json",
                ]
            )
            self.assertEqual(add.returncode, 0, add.stderr)
            item_id = json.loads(add.stdout)["item"]["id"]

            listed = _run_cli(["schedule", "list", "--state-dir", tmp, "--status", "all", "--json"])
            tick = _run_cli(["schedule", "tick", "--state-dir", tmp, "--now", "1", "--json"])
            status = _run_cli(["daemon", "status", "--state-dir", tmp, "--json"])
            pause = _run_cli(["schedule", "pause", item_id, "--state-dir", tmp, "--json"])
            missing = _run_cli(["schedule", "pause", "sched_missing", "--state-dir", tmp])

            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(json.loads(listed.stdout)["items"][0]["id"], item_id)
            self.assertEqual(tick.returncode, 0, tick.stderr)
            tick_payload = json.loads(tick.stdout)
            self.assertEqual(tick_payload["processed"][0]["scheduled_item_id"], item_id)
            self.assertEqual(tick_payload["queue"]["counts"]["pending"], 1)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)["scheduled"]["counts"]["cron"]["completed"], 1)
            self.assertEqual(pause.returncode, 0, pause.stderr)
            self.assertEqual(json.loads(pause.stdout)["item"]["status"], "paused")
            self.assertEqual(missing.returncode, 1)
            self.assertIn("mnemo: scheduled item not found", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)

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
            missing_run = _run_cli(["runs", "cancel", "run_missing", "--state-dir", tmp])

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
            self.assertEqual(missing_run.returncode, 1)
            self.assertIn("mnemo: run not found: run_missing", missing_run.stderr)
            self.assertNotIn("Traceback", missing_run.stderr)


def _run_cli(
    args: list[str],
    *,
    cwd: Path | None = None,
    env_overrides: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "mnemo", *args],
        cwd=cwd or ROOT,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _mcp_text_frame(message: dict[str, Any]) -> str:
    body = json.dumps(message)
    return f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}"


def _read_mcp_text_frames(text: str) -> list[dict[str, Any]]:
    data = text.encode("utf-8")
    frames: list[dict[str, Any]] = []
    offset = 0
    while offset < len(data):
        header_end = data.find(b"\r\n\r\n", offset)
        separator_length = 4
        if header_end == -1:
            header_end = data.find(b"\n\n", offset)
            separator_length = 2
        if header_end == -1:
            raise AssertionError(f"missing MCP frame separator in {text[offset:]!r}")
        header = data[offset:header_end].decode("ascii")
        content_length: int | None = None
        for line in header.split("\r\n"):
            name, separator, value = line.partition(":")
            if separator and name.casefold() == "content-length":
                content_length = int(value.strip())
        if content_length is None:
            raise AssertionError(f"missing Content-Length in {header!r}")
        body_start = header_end + separator_length
        body_end = body_start + content_length
        frames.append(json.loads(data[body_start:body_end].decode("utf-8")))
        offset = body_end
    return frames


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
        stream_chunks: list[dict[str, Any]] | None = None,
        status: int = 200,
    ) -> None:
        self.response = response
        self.delay_s = delay_s
        self.models_response = models_response or {"data": []}
        self.stream_chunks = stream_chunks
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
                if fake_server.stream_chunks is not None and fake_server.requests[-1]["body"].get("stream"):
                    self._send_sse(fake_server.stream_chunks)
                    return
                self._send_json(fake_server.response)

            def _send_sse(self, chunks: list[dict[str, Any]]) -> None:
                response_body = b"".join(
                    f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
                    for chunk in chunks
                ) + b"data: [DONE]\n\n"
                self.send_response(fake_server.status)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(response_body)
                    self.wfile.flush()
                except BrokenPipeError:
                    pass
                self.close_connection = True

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
