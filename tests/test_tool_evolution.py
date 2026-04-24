from __future__ import annotations

import tempfile
import unittest

from mnemo.tools import ToolEvolutionService
from mnemo.storage import StateStore


class ToolEvolutionTests(unittest.TestCase):
    def test_review_blocks_invalid_candidate_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            candidate_id = store.add_tool_candidate(run_id, "bad_tool", {"risk": "read"})

            result = ToolEvolutionService(store).review_candidate(candidate_id)

            self.assertEqual(result["status"], "blocked:invalid_spec")
            self.assertFalse(result["valid"])
            self.assertIn("missing description", result["errors"])
            self.assertEqual(store.get_tool_candidate(candidate_id)["status"], "blocked:invalid_spec")

    def test_review_blocks_candidate_without_passed_eval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            candidate_id = store.add_tool_candidate(run_id, "reader", _valid_spec("reader"))

            result = ToolEvolutionService(store).review_candidate(candidate_id)

            self.assertEqual(result["status"], "blocked:missing_eval")
            self.assertTrue(result["valid"])
            self.assertEqual(result["passed_eval_case_ids"], [])

    def test_review_marks_valid_candidate_ready_with_passed_eval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            candidate_id = store.add_tool_candidate(run_id, "reader", _valid_spec("reader"))
            case_id = store.add_eval_case(run_id, "reader smoke", {"tool_candidate": "reader"})
            store.update_eval_case_status(case_id, "passed", result={"ok": True})

            result = ToolEvolutionService(store).review_candidate(candidate_id)

            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["valid"])
            self.assertEqual(result["passed_eval_case_ids"], [case_id])
            self.assertEqual(store.get_tool_candidate(candidate_id)["status"], "ready")


def _valid_spec(name: str) -> dict:
    return {
        "name": name,
        "description": "Read a test resource",
        "risk": "read",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }


def _store_with_run(tmp: str) -> tuple[StateStore, str]:
    store = StateStore(tmp)
    store.initialize()
    conversation_id = store.create_conversation("tool evolution")
    mission_id = store.create_mission(conversation_id, "tool evolution tests")
    run_id = store.create_run(conversation_id, mission_id, "tool evolution")
    return store, run_id


if __name__ == "__main__":
    unittest.main()
