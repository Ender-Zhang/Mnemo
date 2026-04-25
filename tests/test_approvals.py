from __future__ import annotations

import tempfile
import unittest

from mnemo.runtime.approvals import resolve_inbox_item_with_actions
from mnemo.storage import StateStore


class ApprovalRuntimeTests(unittest.TestCase):
    def test_invalid_tool_approval_does_not_resolve_or_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("approval validation")
            mission_id = store.create_mission(conversation_id, "approval validation")
            run_id = store.create_run(conversation_id, mission_id, "approve missing tool")
            item_id = store.add_inbox_item(
                category="decision",
                title="Approve missing tool?",
                action_type="tool_approval",
                action_data={
                    "tool_call": {
                        "call_id": "call_missing",
                        "provider": "fake",
                        "tool_name": "missing_tool",
                        "risk": "admin",
                        "arguments": {},
                    },
                },
                source_run_id=run_id,
            )

            with self.assertRaisesRegex(ValueError, "unknown tool"):
                resolve_inbox_item_with_actions(store, item_id, "accepted")

            item = store.get_inbox_item(item_id)
            run_event_types = [event["event_type"] for event in store.get_run_events(run_id)]
            self.assertIsNotNone(item)
            self.assertEqual(item["status"], "open")
            self.assertNotIn("tool.called", run_event_types)
            self.assertNotIn("tool.approval.executed", run_event_types)


if __name__ == "__main__":
    unittest.main()
