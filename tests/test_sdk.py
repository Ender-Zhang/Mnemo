from __future__ import annotations

import tempfile
from pathlib import Path
import sys
import unittest

from mnemo.sdk import MnemoClient, mnemo_core_api_schema
from mnemo.storage import StateStore


class MnemoSdkTests(unittest.TestCase):
    def test_context_returns_prompt_ready_compact_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            store.upsert_memory_page(
                "preferences: zephyr",
                "Project Zephyr reports should be concise and source-backed.",
                confidence=0.92,
            )

            context = MnemoClient(state_dir=tmp).context(
                "Zephyr report",
                agent_role="writing",
                budget_tokens=2500,
            )

            self.assertEqual(context["kind"], "context_block")
            self.assertEqual(context["agent_role"], "writing")
            self.assertTrue(context["messages"])
            self.assertEqual(context["messages"][0]["role"], "system")
            self.assertIn("<system>", context["text"])
            self.assertIn("memory_search", context["metadata"]["tool_schema"]["names"])
            self.assertNotIn("input_schema", str(context["metadata"]["tool_schema"]))
            self.assertNotIn("input_schema", str(context["tool_bundle"]))
            self.assertGreaterEqual(len(context["cards"]["memory"]), 1)

    def test_recall_returns_compact_associative_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            page_id = store.upsert_memory_page(
                "preferences: sdk",
                "SDK integrations should use compact context blocks.",
                confidence=0.88,
            )

            cluster = MnemoClient(state_dir=tmp).recall("SDK integrations", depth=2)

            self.assertEqual(cluster["kind"], "associative_cluster")
            self.assertEqual(cluster["seed"], "SDK integrations")
            self.assertIn("query_plan", cluster)
            self.assertIn(page_id, [item["item_id"] for item in cluster["items"]])
            self.assertNotIn("evidence", str(cluster["items"]))

    def test_context_rejects_diagnostic_none_prompt_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "diagnostic-only"):
                MnemoClient(state_dir=tmp).context("debug", prompt_mode="none")

    def test_capsule_returns_external_runtime_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            page_id = store.upsert_memory_page(
                "preferences: capsule",
                "External harness summaries should be short. FULL_PRIVATE_BODY_SECRET_TOKEN",
                confidence=0.9,
            )

            capsule = MnemoClient(state_dir=tmp).capsule(
                "Inspect failing tests",
                runtime="codex",
                agent_type="coding",
                requested_pages=[page_id, "missing_page"],
                allowed_pages=[page_id],
            )

            self.assertEqual(capsule["kind"], "context_capsule")
            self.assertEqual(capsule["runtime"], "codex")
            self.assertEqual(capsule["return_contract"]["side_effects"], "proposals_only")
            self.assertEqual(capsule["allowed_pages"][0]["id"], page_id)
            self.assertEqual(capsule["requested_pages"]["unresolved"][0]["id"], "missing_page")
            self.assertNotIn("FULL_PRIVATE_BODY_SECRET_TOKEN", str(capsule))
            self.assertNotIn("input_schema", str(capsule))

    def test_external_run_uses_command_runtime_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "adapter.py"
            script.write_text(
                """
import json
import sys

payload = json.loads(sys.stdin.read())
print(json.dumps({
    "summary": "sdk adapter " + payload["capsule"]["capsule_id"],
    "evidence": [{"task": payload["task"]}],
    "unexpected_direct_write": True
}))
""".strip(),
                encoding="utf-8",
            )

            result = MnemoClient(state_dir=tmp).external_run(
                "SDK external runtime",
                command=[sys.executable, str(script)],
                timeout_s=5.0,
            )

            self.assertEqual(result["kind"], "external_runtime_result")
            self.assertTrue(result["run_id"].startswith("run_"))
            self.assertIn("sdk adapter capsule_", result["proposal"]["summary"])
            self.assertIn("unexpected_direct_write", result["ignored_fields"])

    def test_run_replay_and_evaluate_reuse_existing_harnesses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = MnemoClient(state_dir=tmp)

            result = client.run("remember: SDK should reuse Mnemo runtime services")
            replay = client.replay(result["run_id"])
            report = client.evaluate("smoke")
            variant_report = client.evaluate("personalization-core", variants=["no_memory", "full_mnemo"])
            release_report = client.evaluate(release_gate=True)

            self.assertTrue(result["run_id"].startswith("run_"))
            self.assertEqual(result["tool_summary"][0]["tool"], "memory_write_candidate")
            self.assertNotIn("tool_results", result)
            self.assertIn("run.completed", result["event_summary"]["event_types"])
            self.assertTrue(replay["completed"])
            self.assertEqual(report["suite"], "smoke")
            self.assertTrue(report["passed"])
            self.assertEqual(variant_report["kind"], "harness_variant_report")
            self.assertEqual(variant_report["variants"], ["no_memory", "full_mnemo"])
            self.assertTrue(variant_report["passed"])
            self.assertEqual(release_report["kind"], "harness_release_report")
            self.assertTrue(release_report["passed"])
            with self.assertRaisesRegex(ValueError, "release_gate cannot be combined"):
                client.evaluate(release_gate=True, variants=["full_mnemo"])

    def test_schedule_dream_uses_existing_scheduler_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = MnemoClient(state_dir=tmp)

            result = client.schedule_dream(limit=12, min_confidence=0.82)

            self.assertEqual(result["kind"], "scheduled_item")
            self.assertEqual(result["version"], "mnemo.schedule_dream.v1")
            item = result["item"]
            self.assertEqual(item["kind"], "dream")
            self.assertEqual(item["schedule"], "daily")
            self.assertEqual(item["source"], "sdk")
            self.assertEqual(item["metadata"]["source"], "sdk")
            self.assertEqual(item["metadata"]["dream"]["limit"], 12)
            self.assertEqual(item["metadata"]["dream"]["min_confidence"], 0.82)
            self.assertNotIn("dream_report", str(result))

    def test_runtime_status_returns_compact_operational_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = MnemoClient(state_dir=tmp)
            store = StateStore(tmp)
            store.initialize()
            inbox_id = store.add_inbox_item(category="decision", title="Approve compact status")
            client.schedule_dream(schedule="once", next_run_at=0)
            run = client.run("remember: SDK runtime status should stay compact")

            status = client.runtime_status(limit=5)

            self.assertEqual(status["kind"], "runtime_status")
            self.assertIn("queue", status)
            self.assertEqual(status["open_inbox"]["items"][0]["id"], inbox_id)
            self.assertEqual(status["scheduled"]["counts"]["dream"]["active"], 1)
            self.assertEqual(status["recent_runs"][0]["run_id"], run["run_id"])
            self.assertIn("SDK runtime status", status["recent_runs"][0]["input"])
            self.assertNotIn("output_text", str(status))

    def test_api_schema_exposes_core_methods(self) -> None:
        schema = mnemo_core_api_schema()

        self.assertEqual(schema["schema_version"], "mnemo.core_api.v1")
        self.assertEqual(
            set(schema["methods"]),
            {
                "context",
                "recall",
                "capsule",
                "run",
                "external_run",
                "schedule_dream",
                "runtime_status",
                "replay",
                "evaluate",
            },
        )
        self.assertEqual(schema["methods"]["context"]["side_effects"], "read_only")
        self.assertIn("prompt_mode", schema["methods"]["context"]["input_schema"]["properties"])
        self.assertIn("requested_pages", schema["methods"]["capsule"]["input_schema"]["properties"])
        self.assertIn("command", schema["methods"]["external_run"]["input_schema"]["properties"])
        self.assertEqual(schema["methods"]["schedule_dream"]["side_effects"], "writes_scheduled_item")
        self.assertIn("min_confidence", schema["methods"]["schedule_dream"]["input_schema"]["properties"])
        self.assertEqual(schema["methods"]["runtime_status"]["side_effects"], "read_only")
        self.assertIn("limit", schema["methods"]["runtime_status"]["input_schema"]["properties"])
        self.assertIn("variants", schema["methods"]["evaluate"]["input_schema"]["properties"])
        self.assertIn("release_gate", schema["methods"]["evaluate"]["input_schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
