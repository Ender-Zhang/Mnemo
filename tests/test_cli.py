from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_help_works(self) -> None:
        completed = _run_cli(["--help"])
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Mnemo personal AI runtime foundation", completed.stdout)

    def test_init_and_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            init = _run_cli(["init", "--state-dir", tmp])
            self.assertEqual(init.returncode, 0)
            self.assertTrue((Path(tmp) / "state.db").exists())

            run = _run_cli(["run", "remember: CLI should emit JSON", "--state-dir", tmp, "--json"])
            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)
            self.assertTrue(payload["run_id"].startswith("run_"))
            self.assertEqual(payload["tool_results"][0]["name"], "memory_write_candidate")

    def test_run_stream_outputs_ndjson_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _run_cli(["run", "remember: CLI stream", "--state-dir", tmp, "--stream"])

            self.assertEqual(run.returncode, 0, run.stderr)
            events = [json.loads(line) for line in run.stdout.splitlines()]
            event_types = [event["type"] for event in events]
            self.assertIn("action.queued", event_types)
            self.assertIn("action.completed", event_types)
            self.assertEqual(events[-1]["type"], "run.completed")
            self.assertEqual(events[-1]["data"]["result"]["tool_results"][0]["name"], "memory_write_candidate")


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return subprocess.run(
        [sys.executable, "-m", "mnemo", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()
