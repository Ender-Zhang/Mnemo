from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from mnemo.core.models import ToolCallEnvelope, ToolExecutionPolicy
from mnemo.runtime.ledger import RunLedger
from mnemo.storage import StateStore
from mnemo.tools import ToolHarness, ToolRegistry


class StandardToolTests(unittest.TestCase):
    def test_browser_and_app_connectors_are_available_by_default(self) -> None:
        names = {spec.name for spec in ToolRegistry().specs()}

        self.assertIn("browser_open", names)
        self.assertIn("app_open", names)

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

    def test_file_write_defaults_to_state_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            store, run_id, mission_id = _store_with_run(state_dir)
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                policy=ToolExecutionPolicy(allowed_risks=("read", "write", "external", "admin")),
            )

            result = harness.execute(
                ToolCallEnvelope(
                    name="file_write",
                    arguments={"path": "snake.html", "content": "game", "mode": "create"},
                    call_id="call_default_workspace",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertTrue(result.ok)
            self.assertEqual((state_dir / "workspace" / "snake.html").read_text(encoding="utf-8"), "game")
            self.assertFalse((root / "snake.html").exists())

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

    def test_file_read_rejects_binary_files_without_decoded_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            binary_path = workspace / "blob.bin"
            binary_path.write_bytes(b"hello\0secret")
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(store=store, ledger=RunLedger(store), workspace_root=workspace)

            result = harness.execute(
                ToolCallEnvelope(
                    name="file_read",
                    arguments={"path": "blob.bin"},
                    call_id="call_binary",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.result, {})
            self.assertIn("file appears to be binary", result.error or "")
            self.assertEqual(result.evidence[0]["kind"], "tool_error")

    def test_risky_tools_are_denied_by_explicit_strict_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "write")),
            )

            for tool_name, arguments in [
                ("file_write", {"path": "out.txt", "content": "hello"}),
                ("file_patch", {"path": "out.txt", "replacements": [{"old": "hello", "new": "hi"}]}),
                ("web_search", {"query": "example"}),
                ("web_fetch", {"url": "https://example.com"}),
                ("shell_exec", {"command": ["echo", "hello"]}),
                ("browser_open", {"url": "https://example.com", "dry_run": True}),
                ("app_open", {"path": ".", "dry_run": True}),
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

    def test_shell_exec_timeout_returns_failed_tool_result(self) -> None:
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

            result = harness.execute(
                ToolCallEnvelope(
                    name="shell_exec",
                    arguments={
                        "command": [sys.executable, "-c", "import time; time.sleep(1)"],
                        "timeout_s": 0.1,
                    },
                    call_id="call_shell_timeout",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertFalse(result.ok)
            self.assertIn("command timed out after 0.1s", result.error or "")
            self.assertEqual(result.evidence[0]["kind"], "tool_error")

    def test_admin_policy_can_enable_file_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            target = workspace / "notes.txt"
            target.write_text("alpha\nneedle\nomega\n", encoding="utf-8")
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "write", "admin")),
            )

            result = harness.execute(
                ToolCallEnvelope(
                    name="file_patch",
                    arguments={
                        "path": "notes.txt",
                        "replacements": [{"old": "needle", "new": "patched"}],
                    },
                    call_id="call_patch",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertTrue(result.ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\npatched\nomega\n")
            self.assertEqual(result.result["replacements"][0]["count"], 1)
            compact_evidence = result.evidence[0]
            self.assertEqual(compact_evidence["kind"], "file_patch")
            self.assertEqual(compact_evidence["replacement_count"], 1)

    def test_file_patch_blocks_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "write", "admin")),
            )

            result = harness.execute(
                ToolCallEnvelope(
                    name="file_patch",
                    arguments={"path": "../outside.txt", "replacements": [{"old": "secret", "new": "patched"}]},
                    call_id="call_patch_traversal",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertFalse(result.ok)
            self.assertIn("outside the workspace root", result.error or "")
            self.assertEqual(outside.read_text(encoding="utf-8"), "secret")

    def test_file_patch_rejects_ambiguous_replacement_without_replace_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            target = workspace / "notes.txt"
            target.write_text("needle\nneedle\n", encoding="utf-8")
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "write", "admin")),
            )

            rejected = harness.execute(
                ToolCallEnvelope(
                    name="file_patch",
                    arguments={"path": "notes.txt", "replacements": [{"old": "needle", "new": "patched"}]},
                    call_id="call_patch_ambiguous",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )
            accepted = harness.execute(
                ToolCallEnvelope(
                    name="file_patch",
                    arguments={
                        "path": "notes.txt",
                        "replacements": [{"old": "needle", "new": "patched"}],
                        "replace_all": True,
                    },
                    call_id="call_patch_all",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertFalse(rejected.ok)
            self.assertIn("ambiguous", rejected.error or "")
            self.assertTrue(accepted.ok)
            self.assertEqual(accepted.result["replacements"][0]["count"], 2)
            self.assertEqual(target.read_text(encoding="utf-8"), "patched\npatched\n")

    def test_browser_open_dry_run_validates_url_and_returns_compact_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "external")),
            )

            opened = harness.execute(
                ToolCallEnvelope(
                    name="browser_open",
                    arguments={"url": "https://example.com/docs", "dry_run": True},
                    call_id="call_browser",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )
            rejected = harness.execute(
                ToolCallEnvelope(
                    name="browser_open",
                    arguments={"url": "file:///tmp/secret", "dry_run": True},
                    call_id="call_browser_bad",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertTrue(opened.ok)
            self.assertFalse(opened.result["opened"])
            self.assertTrue(opened.result["dry_run"])
            self.assertEqual(opened.evidence[0]["kind"], "browser")
            self.assertFalse(rejected.ok)
            self.assertIn("http or https URL", rejected.error or "")

    def test_web_fetch_rejects_malformed_http_url_before_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "external")),
            )

            with patch("mnemo.tools.standard.urlopen") as urlopen:
                result = harness.execute(
                    ToolCallEnvelope(
                        name="web_fetch",
                        arguments={"url": "https:///missing-host"},
                        call_id="call_web_fetch_bad_url",
                    ),
                    run_id=run_id,
                    mission_id=mission_id,
                )

            self.assertFalse(result.ok)
            self.assertEqual(result.result, {})
            self.assertIn("http or https URL", result.error or "")
            self.assertEqual(result.evidence[0]["kind"], "tool_error")
            urlopen.assert_not_called()

    def test_web_fetch_blocks_private_network_urls_before_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "external")),
            )

            with patch("mnemo.tools.standard.build_opener") as build_opener:
                result = harness.execute(
                    ToolCallEnvelope(
                        name="web_fetch",
                        arguments={"url": "http://127.0.0.1/admin"},
                        call_id="call_web_fetch_private_url",
                    ),
                    run_id=run_id,
                    mission_id=mission_id,
                )

            self.assertFalse(result.ok)
            self.assertEqual(result.result, {})
            self.assertIn("private or internal network address", result.error or "")
            self.assertEqual(result.evidence[0]["kind"], "tool_error")
            build_opener.assert_not_called()

    def test_web_fetch_blocks_metadata_urls_even_when_private_urls_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "external")),
            )

            with patch.dict("os.environ", {"MNEMO_ALLOW_PRIVATE_WEB_URLS": "true"}), patch(
                "mnemo.tools.standard.build_opener"
            ) as build_opener:
                result = harness.execute(
                    ToolCallEnvelope(
                        name="web_fetch",
                        arguments={"url": "http://169.254.169.254/latest/meta-data"},
                        call_id="call_web_fetch_metadata_url",
                    ),
                    run_id=run_id,
                    mission_id=mission_id,
                )

            self.assertFalse(result.ok)
            self.assertEqual(result.result, {})
            self.assertIn("private or internal network address", result.error or "")
            build_opener.assert_not_called()

    def test_web_fetch_extracts_readable_html_text(self) -> None:
        html = b"""
        <html>
          <head><title>Example Domain</title><style>.hidden {}</style></head>
          <body><h1>Example Domain</h1><script>secret()</script><p>Readable text.</p></body>
        </html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "external")),
            )

            with patch("mnemo.tools.standard._fetch_http") as fetch_http:
                fetch_http.return_value = {
                    "final_url": "https://93.184.216.34",
                    "status": 200,
                    "headers": _Headers({"content-type": "text/html; charset=utf-8"}),
                    "raw": html,
                    "bytes_read": len(html),
                    "truncated": False,
                }
                result = harness.execute(
                    ToolCallEnvelope(
                        name="web_fetch",
                        arguments={"url": "https://93.184.216.34"},
                        call_id="call_web_fetch_html",
                    ),
                    run_id=run_id,
                    mission_id=mission_id,
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.result["title"], "Example Domain")
            self.assertIn("Example Domain", result.result["text"])
            self.assertIn("Readable text.", result.result["text"])
            self.assertNotIn("<html", result.result["text"].casefold())
            self.assertNotIn("secret()", result.result["text"])
            self.assertEqual(result.evidence[0]["kind"], "web_page")

    def test_web_search_parses_compact_result_metadata(self) -> None:
        html = """
        <html>
          <body>
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs">Example Docs</a>
            <a class="result__snippet">Compact result snippet.</a>
            <a class="result__a" href="https://example.org/news">Example News</a>
            <div class="result__snippet">Second snippet.</div>
          </body>
        </html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "external")),
            )

            with patch("mnemo.tools.standard._fetch_http") as fetch_http:
                fetch_http.return_value = {
                    "final_url": "https://duckduckgo.com/html/?q=mnemo",
                    "status": 200,
                    "headers": _Headers({"content-type": "text/html; charset=utf-8"}),
                    "raw": html.encode("utf-8"),
                    "bytes_read": len(html.encode("utf-8")),
                    "truncated": False,
                }
                result = harness.execute(
                    ToolCallEnvelope(
                        name="web_search",
                        arguments={"query": "mnemo", "limit": 2},
                        call_id="call_web_search",
                    ),
                    run_id=run_id,
                    mission_id=mission_id,
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.result["source"], "duckduckgo_html")
            self.assertEqual(result.result["count"], 2)
            self.assertEqual(result.result["results"][0]["url"], "https://example.com/docs")
            self.assertEqual(result.result["results"][0]["title"], "Example Docs")
            self.assertEqual(result.result["results"][0]["snippet"], "Compact result snippet.")
            self.assertEqual(result.evidence[0]["kind"], "web_search")

    def test_app_open_dry_run_is_workspace_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            docs = workspace / "docs"
            docs.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            store, run_id, mission_id = _store_with_run(root / "state")
            harness = ToolHarness(
                store=store,
                ledger=RunLedger(store),
                workspace_root=workspace,
                policy=ToolExecutionPolicy(allowed_risks=("read", "admin")),
            )

            opened = harness.execute(
                ToolCallEnvelope(
                    name="app_open",
                    arguments={"path": "docs", "dry_run": True},
                    call_id="call_app",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )
            rejected = harness.execute(
                ToolCallEnvelope(
                    name="app_open",
                    arguments={"path": "../outside.txt", "dry_run": True},
                    call_id="call_app_bad",
                ),
                run_id=run_id,
                mission_id=mission_id,
            )

            self.assertTrue(opened.ok)
            self.assertEqual(opened.result["path"], "docs")
            self.assertTrue(opened.result["is_directory"])
            self.assertFalse(opened.result["opened"])
            self.assertEqual(opened.evidence[0]["kind"], "app")
            self.assertFalse(rejected.ok)
            self.assertIn("outside the workspace root", rejected.error or "")


def _store_with_run(path: Path) -> tuple[StateStore, str, str]:
    store = StateStore(path)
    store.initialize()
    conversation_id = store.create_conversation("standard tools")
    mission_id = store.create_mission(conversation_id, "standard tool tests")
    run_id = store.create_run(conversation_id, mission_id, "standard tools")
    return store, run_id, mission_id


class _Headers(dict):
    def get_content_charset(self) -> str:
        content_type = str(self.get("content-type", ""))
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("charset="):
                return part.split("=", 1)[1]
        return "utf-8"


if __name__ == "__main__":
    unittest.main()
