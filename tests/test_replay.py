from __future__ import annotations

import tempfile
import unittest

from mnemo.core.models import RunRequest
from mnemo.evals import replay_summary
from mnemo.runtime import stream_local
from mnemo.runtime.ledger import RunLedger
from mnemo.storage import StateStore


class ReplayTests(unittest.TestCase):
    def test_run_writes_jsonl_trace_and_chat_events_can_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events = list(stream_local(RunRequest(message="remember: replayable", state_dir=tmp)))
            run_id = events[-1].run_id
            ledger = RunLedger(StateStore(tmp))

            trace = ledger.load_trace(run_id)
            chat_events = ledger.chat_events(run_id)

            self.assertTrue(ledger.trace_path(run_id).exists())
            self.assertGreater(len(trace), 0)
            self.assertEqual(chat_events[0]["type"], "turn.started")
            self.assertEqual(chat_events[-1]["type"], "run.completed")

    def test_events_since_filters_by_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events = list(stream_local(RunRequest(message="remember: since filter", state_dir=tmp)))
            run_id = events[-1].run_id
            ledger = RunLedger(StateStore(tmp))
            all_events = ledger.events(run_id)
            later_events = ledger.events_since(run_id, since=all_events[0]["seq"])

            self.assertEqual(len(later_events), len(all_events) - 1)
            self.assertGreater(later_events[0]["seq"], all_events[0]["seq"])

    def test_replay_summary_supports_deterministic_dry_run_and_live_tools_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events = list(stream_local(RunRequest(message="search: replay live tools", state_dir=tmp)))
            run_id = events[-1].run_id

            deterministic = replay_summary(tmp, run_id)
            dry_run = replay_summary(tmp, run_id, mode="dry-run")
            live_tools = replay_summary(tmp, run_id, mode="live-tools")

            self.assertEqual(deterministic["mode"], "deterministic")
            self.assertTrue(deterministic["passed"])
            self.assertTrue(deterministic["checks"][0]["passed"])
            self.assertEqual(dry_run["mode"], "dry_run")
            self.assertFalse(dry_run["dry_run"]["model_called"])
            self.assertFalse(dry_run["dry_run"]["tools_called"])
            self.assertEqual(dry_run["dry_run"]["tool_plan"][0]["tool_name"], "memory_search")
            self.assertEqual(live_tools["mode"], "live_tools")
            self.assertTrue(live_tools["passed"])
            self.assertEqual(live_tools["live_tools"]["summary"]["replayed"], 1)
            self.assertEqual(live_tools["live_tools"]["summary"]["mismatched"], 0)

    def test_live_tools_replay_skips_side_effecting_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events = list(stream_local(RunRequest(message="remember: replay should skip writes", state_dir=tmp)))
            run_id = events[-1].run_id

            live_tools = replay_summary(tmp, run_id, mode="live-tools")

            self.assertTrue(live_tools["passed"])
            self.assertEqual(live_tools["live_tools"]["summary"]["replayed"], 0)
            self.assertEqual(live_tools["live_tools"]["summary"]["skipped"], 1)
            self.assertEqual(live_tools["live_tools"]["items"][0]["reason"], "not_safe_for_live_replay")

    def test_replay_compare_reports_category_diffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = list(stream_local(RunRequest(message="remember: first replay memory", state_dir=tmp)))[-1].run_id
            second = list(stream_local(RunRequest(message="remember: second replay memory", state_dir=tmp)))[-1].run_id

            report = replay_summary(tmp, first, compare_run_id=second)

            self.assertFalse(report["passed"])
            self.assertTrue(report["diff"]["changed"])
            self.assertIn("memory", report["diff"]["changed_categories"])


if __name__ == "__main__":
    unittest.main()
