from __future__ import annotations

import tempfile
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

    def test_run_replay_and_evaluate_reuse_existing_harnesses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = MnemoClient(state_dir=tmp)

            result = client.run("remember: SDK should reuse Mnemo runtime services")
            replay = client.replay(result["run_id"])
            report = client.evaluate("smoke")
            variant_report = client.evaluate("personalization-core", variants=["no_memory", "full_mnemo"])

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

    def test_api_schema_exposes_core_methods(self) -> None:
        schema = mnemo_core_api_schema()

        self.assertEqual(schema["schema_version"], "mnemo.core_api.v1")
        self.assertEqual(set(schema["methods"]), {"context", "recall", "capsule", "run", "replay", "evaluate"})
        self.assertEqual(schema["methods"]["context"]["side_effects"], "read_only")
        self.assertIn("prompt_mode", schema["methods"]["context"]["input_schema"]["properties"])
        self.assertIn("requested_pages", schema["methods"]["capsule"]["input_schema"]["properties"])
        self.assertIn("variants", schema["methods"]["evaluate"]["input_schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
