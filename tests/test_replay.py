from __future__ import annotations

import tempfile
import unittest

from mnemo.core.models import RunRequest
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


if __name__ == "__main__":
    unittest.main()
