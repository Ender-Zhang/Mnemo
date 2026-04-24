from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mnemo.storage import StateStore


class StateStoreTests(unittest.TestCase):
    def test_initialize_creates_schema_and_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()

            self.assertTrue((Path(tmp) / "state.db").exists())
            self.assertTrue((Path(tmp) / "wiki").is_dir())
            self.assertTrue((Path(tmp) / "skills").is_dir())
            self.assertTrue((Path(tmp) / "runs").is_dir())
            self.assertTrue((Path(tmp) / "artifacts").is_dir())

    def test_run_ledger_events_are_sequenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "hello")

            first = store.append_event(run_id, "request.received", {"message": "hello"})
            second = store.append_event(run_id, "run.completed", {"status": "completed"})

            events = store.get_run_events(run_id)
            self.assertEqual((first, second), (1, 2))
            self.assertEqual([event["seq"] for event in events], [1, 2])
            self.assertEqual(events[0]["payload"]["message"], "hello")

    def test_memory_candidate_search_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "remember")

            candidate_id = store.add_memory_candidate(
                run_id,
                "User prefers concise engineering updates",
                dimension="communication",
                confidence=0.8,
                evidence=[{"kind": "test"}],
            )

            matches = store.search_memory_candidates("concise")
            self.assertEqual(matches[0]["id"], candidate_id)
            self.assertEqual(store.get_memory_candidate(candidate_id)["claim"], matches[0]["claim"])


if __name__ == "__main__":
    unittest.main()
