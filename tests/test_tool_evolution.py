from __future__ import annotations

import tempfile
import unittest

from mnemo.core.errors import NotFoundError
from mnemo.tools import ToolEvolutionService, ToolRegistry
from mnemo.storage import StateStore


class ToolEvolutionTests(unittest.TestCase):
    def test_review_and_install_missing_candidate_raise_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, _run_id = _store_with_run(tmp)
            service = ToolEvolutionService(store)

            with self.assertRaisesRegex(NotFoundError, "tool candidate not found: missing_candidate"):
                service.review_candidate("missing_candidate")
            with self.assertRaisesRegex(NotFoundError, "tool candidate not found: missing_candidate"):
                service.install_candidate(
                    "missing_candidate",
                    available_tools={spec.name: spec for spec in ToolRegistry().specs()},
                )

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

    def test_install_ready_alias_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            candidate_id = store.add_tool_candidate(run_id, "lookup_memory", _alias_spec("lookup_memory"))
            _mark_ready(store, run_id, candidate_id, "lookup_memory")

            result = ToolEvolutionService(store).install_candidate(
                candidate_id,
                available_tools={spec.name: spec for spec in ToolRegistry().specs()},
            )

            installed = store.get_generated_tool("lookup_memory")
            self.assertTrue(result["installed"])
            self.assertEqual(result["status"], "installed")
            self.assertEqual(result["target_tool"], "memory_search")
            self.assertEqual(store.get_tool_candidate(candidate_id)["status"], "installed")
            self.assertEqual(installed["implementation"]["argument_map"]["query"]["from"], "term")

    def test_install_blocks_non_ready_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            candidate_id = store.add_tool_candidate(run_id, "lookup_memory", _alias_spec("lookup_memory"))

            result = ToolEvolutionService(store).install_candidate(
                candidate_id,
                available_tools={spec.name: spec for spec in ToolRegistry().specs()},
            )

            self.assertFalse(result["installed"])
            self.assertEqual(result["status"], "blocked:not_ready")
            self.assertIsNone(store.get_generated_tool("lookup_memory"))

    def test_install_rejects_unknown_target_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            spec = _alias_spec("lookup_memory")
            spec["implementation"]["target_tool"] = "missing_tool"
            candidate_id = store.add_tool_candidate(run_id, "lookup_memory", spec)
            _mark_ready(store, run_id, candidate_id, "lookup_memory")

            result = ToolEvolutionService(store).install_candidate(
                candidate_id,
                available_tools={spec.name: spec for spec in ToolRegistry().specs()},
            )

            self.assertFalse(result["installed"])
            self.assertEqual(result["status"], "blocked:install_invalid")
            self.assertIn("target tool is not available: missing_tool", result["errors"])

    def test_install_rejects_permission_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            spec = _alias_spec("write_file")
            spec["risk"] = "read"
            spec["implementation"] = {"type": "alias", "target_tool": "file_write", "argument_map": {}}
            candidate_id = store.add_tool_candidate(run_id, "write_file", spec)
            _mark_ready(store, run_id, candidate_id, "write_file")

            result = ToolEvolutionService(store).install_candidate(
                candidate_id,
                available_tools={spec.name: spec for spec in ToolRegistry().specs()},
            )

            self.assertFalse(result["installed"])
            self.assertEqual(result["status"], "blocked:install_invalid")
            self.assertIn("generated tool risk cannot be lower than target tool risk", result["errors"])

    def test_install_rejects_existing_tool_name_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            spec = _alias_spec("memory_read")
            spec["implementation"]["target_tool"] = "memory_search"
            candidate_id = store.add_tool_candidate(run_id, "memory_read", spec)
            _mark_ready(store, run_id, candidate_id, "memory_read")

            result = ToolEvolutionService(store).install_candidate(
                candidate_id,
                available_tools={spec.name: spec for spec in ToolRegistry().specs()},
            )

            self.assertFalse(result["installed"])
            self.assertEqual(result["status"], "blocked:install_invalid")
            self.assertIn("generated tool name conflicts with existing tool: memory_read", result["errors"])


def _valid_spec(name: str) -> dict:
    return {
        "name": name,
        "description": "Read a test resource",
        "risk": "read",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }


def _alias_spec(name: str) -> dict:
    spec = _valid_spec(name)
    spec["description"] = "Lookup memory with a focused argument name"
    spec["input_schema"] = {
        "type": "object",
        "properties": {"term": {"type": "string"}},
        "required": ["term"],
        "additionalProperties": False,
    }
    spec["implementation"] = {
        "type": "alias",
        "target_tool": "memory_search",
        "argument_map": {"query": {"from": "term"}, "limit": {"const": 5}},
    }
    return spec


def _mark_ready(store: StateStore, run_id: str, candidate_id: str, name: str) -> None:
    case_id = store.add_eval_case(run_id, f"{name} smoke", {"tool_candidate": name})
    store.update_eval_case_status(case_id, "passed", result={"ok": True})
    review = ToolEvolutionService(store).review_candidate(candidate_id)
    assert review["status"] == "ready"


def _store_with_run(tmp: str) -> tuple[StateStore, str]:
    store = StateStore(tmp)
    store.initialize()
    conversation_id = store.create_conversation("tool evolution")
    mission_id = store.create_mission(conversation_id, "tool evolution tests")
    run_id = store.create_run(conversation_id, mission_id, "tool evolution")
    return store, run_id


if __name__ == "__main__":
    unittest.main()
