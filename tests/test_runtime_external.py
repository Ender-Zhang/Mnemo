from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from mnemo.runtime import ExternalRunRequest, ExternalRuntimeError, run_external
from mnemo.storage import StateStore


class ExternalRuntimeTests(unittest.TestCase):
    def test_command_runtime_receives_capsule_and_records_proposals_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            page_id = store.upsert_memory_page(
                "preferences: external runtime",
                "External runtime reports should be concise. FULL_PRIVATE_BODY_SECRET_TOKEN",
                confidence=0.9,
            )
            script = Path(tmp) / "adapter.py"
            script.write_text(
                """
import json
import sys

payload = json.loads(sys.stdin.read())
serialized = json.dumps(payload)
print("adapter log line")
print(json.dumps({
    "summary": "adapter completed saw_secret=%s" % ("FULL_PRIVATE_BODY_SECRET_TOKEN" in serialized),
    "evidence": [{"capsule_id": payload["capsule"]["capsule_id"]}],
    "files_changed": ["none"],
    "memory_observations": [{"summary": "candidate observation only"}],
    "skill_patches": [{"summary": "candidate skill patch only"}],
    "memory_writes": [{"claim": "must not be written"}],
    "tool_calls": [{"name": "memory_write_candidate"}],
    "confidence": 0.84
}))
""".strip(),
                encoding="utf-8",
            )

            result = run_external(
                ExternalRunRequest(
                    task="Inspect external adapter",
                    state_dir=tmp,
                    command=[sys.executable, str(script)],
                    runtime="codex",
                    agent_type="coding",
                    requested_pages=[page_id],
                    allowed_pages=[page_id],
                    timeout_s=5.0,
                )
            )

            self.assertEqual(result["kind"], "external_runtime_result")
            self.assertEqual(result["runtime"], "codex")
            self.assertTrue(result["run_id"].startswith("run_"))
            self.assertIn("saw_secret=False", result["proposal"]["summary"])
            self.assertEqual(result["proposal"]["confidence"], 0.84)
            self.assertIn("memory_writes", result["ignored_fields"])
            self.assertIn("tool_calls", result["ignored_fields"])
            self.assertNotIn("FULL_PRIVATE_BODY_SECRET_TOKEN", json.dumps(result))

            events = store.get_run_events(result["run_id"])
            event_types = [event["event_type"] for event in events]
            self.assertIn("external.capsule.prepared", event_types)
            self.assertIn("external.runtime.started", event_types)
            self.assertIn("external.runtime.completed", event_types)
            self.assertIn("external.result.proposed", event_types)
            self.assertIn("memory.observation.proposed", event_types)
            self.assertIn("skill.patch.proposed", event_types)
            self.assertIn("runtime.boundary_violation", event_types)
            self.assertIn("run.completed", event_types)
            self.assertEqual(store.get_run(result["run_id"])["status"], "completed")
            self.assertEqual(store.list_memory_candidates(status=None), [])

    def test_command_runtime_failures_are_normalized_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fail.py"
            script.write_text(
                "import sys\nsys.stderr.write('adapter exploded')\nsys.exit(3)\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ExternalRuntimeError, "exited with code 3"):
                run_external(
                    ExternalRunRequest(
                        task="Fail external adapter",
                        state_dir=tmp,
                        command=[sys.executable, str(script)],
                        timeout_s=5.0,
                    )
                )

            store = StateStore(tmp)
            store.initialize()
            runs = store.list_runs(status="failed", limit=5)
            self.assertEqual(len(runs), 1)
            events = store.get_run_events(runs[0]["id"])
            event_types = [event["event_type"] for event in events]
            self.assertIn("external.runtime.failed", event_types)
            self.assertIn("run.completed", event_types)


if __name__ == "__main__":
    unittest.main()
