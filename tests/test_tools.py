from __future__ import annotations

import tempfile
import unittest

from mnemo.core.models import ToolCallEnvelope, ToolExecutionPolicy, ToolSpec
from mnemo.runtime.ledger import RunLedger
from mnemo.storage import StateStore
from mnemo.tools import ToolHarness, ToolRegistry, compact_tool_result


class ToolHarnessBoundaryTests(unittest.TestCase):
    def test_harness_blocks_disallowed_risk_without_calling_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id, mission_id = _store_with_run(tmp)
            registry = ToolRegistry()
            called = {"value": False}

            def handler(args, context):
                called["value"] = True
                return {"ok": True}

            registry.register(
                ToolSpec(
                    name="external_fetch",
                    description="Fetch an external URL",
                    risk="external",
                    input_schema={"type": "object", "properties": {}, "required": []},
                ),
                handler,
            )
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                registry=registry,
                policy=ToolExecutionPolicy(allowed_risks=("read", "write")),
            )

            result = harness.execute(
                ToolCallEnvelope(name="external_fetch", arguments={}, call_id="call_external", risk="external"),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertFalse(called["value"])
            self.assertFalse(result.ok)
            self.assertIn("not allowed", result.summary)
            events = store.get_run_events(run_id)
            self.assertIn("tool.denied", [event["event_type"] for event in events])

    def test_compact_tool_result_keeps_summary_and_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id, mission_id = _store_with_run(tmp)
            result = ToolHarness(store=store, ledger=RunLedger(store)).execute(
                ToolCallEnvelope(
                    name="memory_write_candidate",
                    arguments={"claim": "User prefers compact tool results"},
                    call_id="call_memory",
                    risk="write",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            compact = compact_tool_result(result)

            self.assertTrue(compact["ok"])
            self.assertEqual(compact["tool"], "memory_write_candidate")
            self.assertIn("summary", compact)
            self.assertIn("evidence", compact)
            self.assertNotIn("result", compact)

    def test_skill_view_records_usage_and_outcome_tool_records_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id, mission_id = _store_with_run(tmp)
            store.upsert_skill("writer", "Draft concise notes", "Full skill body", status="active")
            harness = ToolHarness(store=store, ledger=RunLedger(store))

            viewed = harness.execute(
                ToolCallEnvelope(
                    name="skill_view",
                    arguments={"name": "writer"},
                    call_id="call_skill_view",
                    risk="read",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )
            outcome = harness.execute(
                ToolCallEnvelope(
                    name="skill_record_outcome",
                    arguments={
                        "name": "writer",
                        "outcome": "success",
                        "score": 0.75,
                        "evidence": [{"kind": "test"}],
                    },
                    call_id="call_skill_outcome",
                    risk="write",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            usage = store.list_skill_usage("writer")

            self.assertTrue(viewed.ok)
            self.assertTrue(outcome.ok)
            self.assertEqual([event["event_type"] for event in usage], ["outcome", "viewed"])
            self.assertEqual(usage[0]["score"], 0.75)
            self.assertEqual(usage[0]["evidence"], [{"kind": "test"}])
            self.assertIn("Recorded skill outcome", outcome.summary)

    def test_skill_record_outcome_rejects_out_of_range_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id, mission_id = _store_with_run(tmp)
            harness = ToolHarness(store=store, ledger=RunLedger(store))

            result = harness.execute(
                ToolCallEnvelope(
                    name="skill_record_outcome",
                    arguments={"name": "writer", "outcome": "success", "score": 2},
                    call_id="call_skill_bad_score",
                    risk="write",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertFalse(result.ok)
            self.assertIn("between -1 and 1", result.error or "")
            self.assertEqual(store.list_skill_usage("writer"), [])

    def test_skill_view_missing_skill_does_not_record_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id, mission_id = _store_with_run(tmp)
            harness = ToolHarness(store=store, ledger=RunLedger(store))

            result = harness.execute(
                ToolCallEnvelope(
                    name="skill_view",
                    arguments={"name": "missing"},
                    call_id="call_skill_missing",
                    risk="read",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertFalse(result.ok)
            self.assertEqual(store.list_skill_usage("missing"), [])

    def test_skill_record_outcome_defaults_score_from_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id, mission_id = _store_with_run(tmp)
            harness = ToolHarness(store=store, ledger=RunLedger(store))

            result = harness.execute(
                ToolCallEnvelope(
                    name="skill_record_outcome",
                    arguments={"name": "writer", "outcome": "failure"},
                    call_id="call_skill_default_score",
                    risk="write",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            usage = store.list_skill_usage("writer")
            self.assertTrue(result.ok)
            self.assertEqual(usage[0]["score"], -1.0)


def _store_with_run(tmp: str) -> tuple[StateStore, str, str]:
    store = StateStore(tmp)
    store.initialize()
    conversation_id = store.create_conversation("tools")
    mission_id = store.create_mission(conversation_id, "tool tests")
    run_id = store.create_run(conversation_id, mission_id, "tool")
    return store, run_id, mission_id


if __name__ == "__main__":
    unittest.main()
