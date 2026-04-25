from __future__ import annotations

import tempfile
import unittest

from mnemo.core.models import RunRequest
from mnemo.evals import EvalHarness, list_suites, list_variants, replay_summary
from mnemo.runtime import stream_local


class EvalHarnessTests(unittest.TestCase):
    def test_personalization_core_suite_passes(self) -> None:
        report = EvalHarness().run_suite("personalization-core")

        self.assertTrue(report.passed)
        self.assertEqual(report.case_count, 4)
        self.assertEqual(report.failed_count, 0)
        self.assertTrue(all(case.passed for case in report.cases))
        self.assertIn("personalization-core", list_suites())

    def test_memory_safety_suite_passes(self) -> None:
        report = EvalHarness().run_suite("memory-safety")

        self.assertTrue(report.passed)
        self.assertEqual(report.case_count, 5)
        self.assertEqual(report.failed_count, 0)
        self.assertIn("memory-safety", list_suites())
        assertion_names = {
            assertion.name
            for case in report.cases
            for step in case.steps
            for assertion in step.assertions
        }
        self.assertIn("stable_pages_not_created", assertion_names)
        self.assertIn("candidate_needs_review", assertion_names)
        self.assertIn("snapshot_omits_full_page_tail", assertion_names)
        self.assertIn("candidate_needs_prompt_injection_review", assertion_names)

    def test_skill_evolution_suite_passes(self) -> None:
        report = EvalHarness().run_suite("skill-evolution")

        self.assertTrue(report.passed)
        self.assertEqual(report.case_count, 4)
        self.assertEqual(report.failed_count, 0)
        self.assertIn("skill-evolution", list_suites())
        assertion_names = {
            assertion.name
            for case in report.cases
            for step in case.steps
            for assertion in step.assertions
        }
        self.assertIn("crystallized_body_omits_raw_payload", assertion_names)
        self.assertIn("skill_review_uses_passed_eval", assertion_names)
        self.assertIn("skill_review_blocks_failed_eval", assertion_names)
        self.assertIn("skill_cards_omit_full_body_secret", assertion_names)

    def test_external_harness_suite_passes(self) -> None:
        report = EvalHarness().run_suite("external-harness")

        self.assertTrue(report.passed)
        self.assertEqual(report.case_count, 1)
        self.assertEqual(report.failed_count, 0)
        self.assertIn("external-harness", list_suites())
        assertion_names = {
            assertion.name
            for case in report.cases
            for step in case.steps
            for assertion in step.assertions
        }
        self.assertIn("omits_raw_session_transcript", assertion_names)
        self.assertIn("boundary_is_proposals_only", assertion_names)

    def test_variant_report_compares_core_variants(self) -> None:
        report = EvalHarness().run_variant_report("personalization-core")
        payload = report.as_dict()

        self.assertTrue(report.passed)
        self.assertEqual(payload["kind"], "harness_variant_report")
        self.assertEqual(payload["variants"], ["no_memory", "skills_only", "full_mnemo"])
        self.assertEqual(payload["baseline_variant"], "no_memory")
        self.assertEqual(payload["target_variant"], "full_mnemo")
        self.assertIn("no_memory", list_variants())
        metrics = {item["variant"]: item["metrics"] for item in payload["reports"]}
        self.assertEqual(metrics["full_mnemo"]["task_success"], 1.0)
        self.assertLess(metrics["no_memory"]["task_success"], metrics["full_mnemo"]["task_success"])
        self.assertTrue(payload["gates"]["passed"])
        compact_suite = payload["reports"][0]["suite"]
        self.assertIn("failed_assertions", compact_suite["cases"][0])
        self.assertEqual(
            set(compact_suite["cases"][0]),
            {"case_id", "name", "passed", "failed_assertions"},
        )
        self.assertNotIn("detail", str(compact_suite))
        self.assertNotIn("steps", str(compact_suite))

    def test_variant_report_rejects_unknown_variant(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown harness variant"):
            EvalHarness().run_variant_report("personalization-core", variants=["missing"])

    def test_replay_summary_reads_jsonl_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events = list(stream_local(RunRequest(message="remember: harness replay", state_dir=tmp)))
            run_id = events[-1].run_id

            summary = replay_summary(tmp, run_id)

            self.assertTrue(summary["completed"])
            self.assertGreater(summary["event_count"], 0)
            self.assertIn("chat.event", summary["event_types"])


if __name__ == "__main__":
    unittest.main()
