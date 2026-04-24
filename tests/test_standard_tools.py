from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from mnemo.core.models import ToolCallEnvelope, ToolExecutionPolicy
from mnemo.runtime.ledger import RunLedger
from mnemo.storage import StateStore
from mnemo.tools import ToolHarness


class StandardToolTests(unittest.TestCase):
    def test_file_search_and_read_are_available_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "notes").mkdir()
            (workspace / "notes" / "plan.txt").write_text("alpha\nneedle line\n", encoding="utf-8")
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(store=store, ledger=RunLedger(store), workspace_root=workspace)

            search = harness.execute(
                ToolCallEnvelope(
                    name="file_search",
                    arguments={"query": "needle", "root": ".", "limit": 5},
                    call_id="call_search",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )
            read = harness.execute(
                ToolCallEnvelope(
                    name="file_read",
                    arguments={"path": "notes/plan.txt", "max_bytes": 100},
                    call_id="call_read",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertTrue(search.ok)
            self.assertEqual(search.result["matches"][0]["path"], "notes/plan.txt")
            self.assertTrue(read.ok)
            self.assertEqual(read.result["text"], "alpha\nneedle line\n")

    def test_file_read_blocks_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(store=store, ledger=RunLedger(store), workspace_root=workspace)

            result = harness.execute(
                ToolCallEnvelope(
                    name="file_read",
                    arguments={"path": "../outside.txt"},
                    call_id="call_traversal",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertFalse(result.ok)
            self.assertIn("outside the workspace root", result.error or "")

    def test_risky_tools_are_denied_by_default_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(store=store, ledger=RunLedger(store), workspace_root=workspace)

            for tool_name, arguments in [
                ("file_write", {"path": "out.txt", "content": "hello"}),
                ("web_fetch", {"url": "https://example.com"}),
                ("shell_exec", {"command": ["echo", "hello"]}),
            ]:
                with self.subTest(tool_name=tool_name):
                    result = harness.execute(
                        ToolCallEnvelope(
                            name=tool_name,
                            arguments=arguments,
                            call_id=f"call_{tool_name}",
                        ),
                        run_id=run_id,
                        mission_id=mission_id,
                    )
                    self.assertFalse(result.ok)
                    self.assertIn("not allowed", result.summary)

    def test_admin_policy_can_enable_file_write_and_shell_exec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "write", "admin")),
            )

            write = harness.execute(
                ToolCallEnvelope(
                    name="file_write",
                    arguments={"path": "out.txt", "content": "hello\n"},
                    call_id="call_write",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )
            shell = harness.execute(
                ToolCallEnvelope(
                    name="shell_exec",
                    arguments={"command": ["/bin/echo", "done"], "max_output_bytes": 100},
                    call_id="call_shell",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertTrue(write.ok)
            self.assertEqual((workspace / "out.txt").read_text(encoding="utf-8"), "hello\n")
            self.assertTrue(shell.ok)
            self.assertEqual(shell.result["exit_code"], 0)
            self.assertEqual(shell.result["stdout"], "done\n")


def _store_with_run(path: Path) -> tuple[StateStore, str, str]:
    store = StateStore(path)
    store.initialize()
    conversation_id = store.create_conversation("standard tools")
    mission_id = store.create_mission(conversation_id, "standard tool tests")
    run_id = store.create_run(conversation_id, mission_id, "standard tools")
    return store, run_id, mission_id


if __name__ == "__main__":
    unittest.main()
