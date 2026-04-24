from __future__ import annotations

import tempfile
import unittest

from mnemo.core.models import RunRequest
from mnemo.evals import EvalHarness, list_suites, replay_summary
from mnemo.runtime import stream_local


class EvalHarnessTests(unittest.TestCase):
    def test_personalization_core_suite_passes(self) -> None:
        report = EvalHarness().run_suite("personalization-core")

        self.assertTrue(report.passed)
        self.assertEqual(report.case_count, 3)
        self.assertEqual(report.failed_count, 0)
        self.assertTrue(all(case.passed for case in report.cases))
        self.assertIn("personalization-core", list_suites())

    def test_memory_safety_suite_passes(self) -> None:
        report = EvalHarness().run_suite("memory-safety")

        self.assertTrue(report.passed)
        self.assertEqual(report.case_count, 4)
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
