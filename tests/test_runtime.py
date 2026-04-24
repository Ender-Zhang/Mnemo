from __future__ import annotations

import tempfile
import unittest

from mnemo.models import RunRequest
from mnemo.runtime import run_local
from mnemo.storage import StateStore


class LocalRuntimeTests(unittest.TestCase):
    def test_remember_creates_candidate_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_local(RunRequest(message="remember: I prefer concise updates", state_dir=tmp))

            self.assertEqual(result.tool_results[0].name, "memory_write_candidate")
            self.assertTrue(result.tool_results[0].ok)
            self.assertIn("记忆候选", result.response)

            store = StateStore(tmp)
            matches = store.search_memory_candidates("concise")
            events = store.get_run_events(result.run_id)

            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["claim"], "I prefer concise updates")
            self.assertIn("tool.called", [event["event_type"] for event in events])
            self.assertIn("run.completed", [event["event_type"] for event in events])

    def test_followup_reuses_active_mission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = run_local(RunRequest(message="remember: Use direct answers", state_dir=tmp))
            second = run_local(
                RunRequest(
                    message="search: direct answers",
                    state_dir=tmp,
                    conversation_id=first.conversation_id,
                )
            )

            self.assertEqual(first.conversation_id, second.conversation_id)
            self.assertEqual(first.mission_id, second.mission_id)
            self.assertEqual(second.tool_results[0].name, "memory_search")
            self.assertEqual(len(second.tool_results[0].result["matches"]), 1)


if __name__ == "__main__":
    unittest.main()
