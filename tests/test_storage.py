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

    def test_working_notes_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "note")

            note_id = store.add_working_note(
                mission_id,
                run_id,
                "User wants terse implementation updates",
                metadata={"retention": "memory_candidate", "confidence": 0.8},
            )
            open_notes = store.list_working_notes()
            store.update_working_note_status(note_id, "candidate_created", result={"candidate_id": "mem_1"})
            processed = store.list_working_notes(status="candidate_created")

            self.assertEqual(open_notes[0]["id"], note_id)
            self.assertEqual(open_notes[0]["metadata"]["retention"], "memory_candidate")
            self.assertEqual(open_notes[0]["status"], "open")
            self.assertEqual(processed[0]["result"], {"candidate_id": "mem_1"})
            self.assertIsNotNone(processed[0]["processed_at"])

    def test_skill_usage_events_and_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "skill")
            store.upsert_skill("writer", "Draft concise notes", "Body", status="active")

            view_id = store.record_skill_usage(
                run_id,
                "writer",
                "viewed",
                evidence=[{"kind": "tool_call"}],
            )
            outcome_id = store.record_skill_usage(
                run_id,
                "writer",
                "outcome",
                outcome="success",
                score=0.8,
                evidence=[{"kind": "user_feedback"}],
            )

            usage = store.list_skill_usage("writer")
            stats = store.skill_usage_stats()["writer"]

            self.assertEqual({event["id"] for event in usage}, {view_id, outcome_id})
            self.assertEqual(usage[0]["evidence"], [{"kind": "user_feedback"}])
            self.assertEqual(stats["uses"], 2)
            self.assertEqual(stats["views"], 1)
            self.assertEqual(stats["outcomes"], 1)
            self.assertEqual(stats["successes"], 1)
            self.assertEqual(stats["avg_score"], 0.8)

    def test_tool_candidates_and_eval_cases_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "tools")

            candidate_id = store.add_tool_candidate(
                run_id,
                "fetch_page",
                {"description": "Fetch pages", "risk": "read", "input_schema": {"type": "object"}},
            )
            case_id = store.add_eval_case(
                run_id,
                "fetch_page smoke",
                {"tool_candidate": "fetch_page", "assert": "returns text"},
            )
            store.update_tool_candidate_status(candidate_id, "ready")
            store.update_eval_case_status(case_id, "passed", result={"ok": True})

            candidate = store.get_tool_candidate(candidate_id)
            cases = store.list_eval_cases(status="passed", tool_name="fetch_page")
            listed = store.list_tool_candidates(status="ready")

            self.assertEqual(candidate["status"], "ready")
            self.assertEqual(candidate["spec"]["risk"], "read")
            self.assertEqual(listed[0]["id"], candidate_id)
            self.assertEqual(cases[0]["id"], case_id)
            self.assertEqual(cases[0]["case"]["tool_candidate"], "fetch_page")
            self.assertEqual(cases[0]["result"], {"ok": True})

    def test_eval_cases_can_filter_by_skill_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("test")
            mission_id = store.create_mission(conversation_id, "test mission")
            run_id = store.create_run(conversation_id, mission_id, "skills")

            writer_case = store.add_eval_case(run_id, "writer smoke", {"skill_name": "writer"})
            store.add_eval_case(run_id, "reader smoke", {"skill_candidate": "reader"})
            store.update_eval_case_status(writer_case, "passed", result={"ok": True})

            writer_cases = store.list_eval_cases(status="passed", skill_name="writer")
            reader_cases = store.list_eval_cases(skill_name="reader")

            self.assertEqual([case["id"] for case in writer_cases], [writer_case])
            self.assertEqual(reader_cases[0]["case"]["skill_candidate"], "reader")


if __name__ == "__main__":
    unittest.main()
