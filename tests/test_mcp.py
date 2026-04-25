from __future__ import annotations

from io import BytesIO, StringIO
import json
import tempfile
import unittest

from mnemo.mcp import MnemoMcpServer, mcp_tool_descriptors
from mnemo.storage import StateStore


def _mcp_frame(message: dict[str, object]) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


def _read_mcp_frames(data: bytes) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    offset = 0
    while offset < len(data):
        header_end = data.find(b"\r\n\r\n", offset)
        if header_end == -1:
            raise AssertionError(f"missing MCP frame separator in {data[offset:]!r}")
        header = data[offset:header_end].decode("ascii")
        content_length: int | None = None
        for line in header.split("\r\n"):
            name, separator, value = line.partition(":")
            if separator and name.casefold() == "content-length":
                content_length = int(value.strip())
        if content_length is None:
            raise AssertionError(f"missing Content-Length in {header!r}")
        body_start = header_end + 4
        body_end = body_start + content_length
        frames.append(json.loads(data[body_start:body_end].decode("utf-8")))
        offset = body_end
    return frames


class MnemoMcpTests(unittest.TestCase):
    def test_tool_list_exposes_core_surfaces_without_snake_case_schemas(self) -> None:
        tools = mcp_tool_descriptors()
        names = {tool["name"] for tool in tools}

        self.assertTrue(
            {
                "mnemo_context",
                "mnemo_update",
                "mnemo_recall",
                "mnemo_search",
                "mnemo_watch",
                "mnemo_skills",
                "mnemo_tools",
                "mnemo_cron",
                "mnemo_run",
                "mnemo_replay",
                "mnemo_eval",
                "mnemo_runtime_status",
            }.issubset(names)
        )
        self.assertTrue(all("inputSchema" in tool for tool in tools))
        self.assertTrue(all("annotations" in tool for tool in tools))
        self.assertNotIn("input_schema", str(tools))

    def test_context_search_recall_skills_and_tools_are_compact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            page_id = store.upsert_memory_page(
                "preferences: mcp",
                "MCP clients should receive compact cards, not raw traces.",
                confidence=0.91,
            )
            store.upsert_skill("mcp-skill", "Use compact MCP cards", "Keep MCP results short.", status="active")
            server = MnemoMcpServer(state_dir=tmp)

            context = server.call_tool("mnemo_context", {"intent": "compact MCP", "agent_role": "integrator"})
            search = server.call_tool("mnemo_search", {"query": "compact MCP", "limit": 5})
            recall = server.call_tool("mnemo_recall", {"seed": "compact MCP", "limit": 5})
            skills = server.call_tool("mnemo_skills", {"query": "mcp", "limit": 5})
            tools = server.call_tool("mnemo_tools", {"query": "memory", "profile": "minimal.v1"})

            self.assertEqual(context["kind"], "context_block")
            self.assertIn(page_id, [card["id"] for card in search["cards"]])
            self.assertIn(page_id, [item["item_id"] for item in recall["items"]])
            self.assertEqual(skills["cards"][0]["name"], "mcp-skill")
            self.assertTrue(any(card["name"] == "memory_search" for card in tools["cards"]))
            self.assertNotIn("evidence", str(search["cards"]))
            self.assertNotIn("input_schema", str(tools))

    def test_update_writes_memory_candidates_and_working_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = MnemoMcpServer(state_dir=tmp)

            result = server.call_tool(
                "mnemo_update",
                {
                    "source": "unit-test",
                    "facts": [
                        {
                            "claim": "MCP updates should enter memory as candidates.",
                            "dimension": "integration",
                            "confidence": 0.82,
                        }
                    ],
                    "observations": [
                        {
                            "content": "The caller completed an external planning step.",
                            "retention": "ephemeral",
                        }
                    ],
                },
            )

            store = StateStore(tmp)
            store.initialize()
            candidates = store.list_memory_candidates(status=None)
            notes = store.list_working_notes(status=None)
            self.assertEqual(result["kind"], "update_result")
            self.assertEqual(len(result["memory_candidates"]), 1)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["dimension"], "integration")
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["metadata"]["source"], "unit-test")

    def test_run_replay_eval_status_and_scheduled_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = MnemoMcpServer(state_dir=tmp)

            run = server.call_tool("mnemo_run", {"message": "remember: MCP should reuse runtime harnesses"})
            replay = server.call_tool("mnemo_replay", {"run_id": run["run_id"]})
            report = server.call_tool("mnemo_eval", {"suite": "smoke"})
            variants = server.call_tool(
                "mnemo_eval",
                {"suite": "personalization-core", "variants": ["no_memory", "full_mnemo"]},
            )
            watch = server.call_tool(
                "mnemo_watch",
                {"target": "calendar", "instruction": "Check calendar risk", "schedule": "once", "next_run_at": 0},
            )
            cron = server.call_tool(
                "mnemo_cron",
                {"schedule": "once", "message": "remember: MCP cron", "next_run_at": 0},
            )
            status = server.call_tool("mnemo_runtime_status", {"limit": 5})

            self.assertTrue(run["run_id"].startswith("run_"))
            self.assertNotIn("tool_results", run)
            self.assertTrue(replay["completed"])
            self.assertTrue(report["passed"])
            self.assertEqual(variants["kind"], "harness_variant_report")
            self.assertEqual(variants["variants"], ["no_memory", "full_mnemo"])
            self.assertTrue(variants["passed"])
            self.assertEqual(watch["kind"], "scheduled_item")
            self.assertEqual(watch["item"]["kind"], "watch")
            self.assertEqual(cron["item"]["kind"], "cron")
            self.assertEqual(status["kind"], "runtime_status")
            self.assertGreaterEqual(len(status["recent_runs"]), 1)
            self.assertEqual(status["scheduled"]["due"], 2)

    def test_json_rpc_initialize_list_call_errors_and_jsonl_serve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = MnemoMcpServer(state_dir=tmp)

            initialized = server.handle_json_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            listed = server.handle_json_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            called = server.handle_json_rpc(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "mnemo_context", "arguments": {"intent": "json-rpc"}},
                }
            )
            missing = server.handle_json_rpc({"jsonrpc": "2.0", "id": 4, "method": "missing"})

            self.assertEqual(initialized["result"]["serverInfo"]["name"], "mnemo")
            self.assertIn("tools", listed["result"])
            self.assertEqual(called["result"]["structuredContent"]["kind"], "context_block")
            self.assertEqual(missing["error"]["code"], -32601)

            input_stream = StringIO(json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/list"}) + "\n")
            output_stream = StringIO()
            server.serve_jsonl(input_stream=input_stream, output_stream=output_stream)
            response = json.loads(output_stream.getvalue())
            self.assertEqual(response["id"], 5)
            self.assertIn("tools", response["result"])

    def test_content_length_serve_handles_initialize_list_and_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = MnemoMcpServer(state_dir=tmp)
            input_stream = BytesIO(
                b"".join(
                    [
                        _mcp_frame({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
                        _mcp_frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                        _mcp_frame(
                            {
                                "jsonrpc": "2.0",
                                "id": 3,
                                "method": "tools/call",
                                "params": {
                                    "name": "mnemo_context",
                                    "arguments": {"intent": "content-length"},
                                },
                            }
                        ),
                    ]
                )
            )
            output_stream = BytesIO()

            server.serve_content_length(input_stream=input_stream, output_stream=output_stream)

            responses = _read_mcp_frames(output_stream.getvalue())
            self.assertEqual([response["id"] for response in responses], [1, 2, 3])
            self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "mnemo")
            self.assertIn("tools", responses[1]["result"])
            self.assertEqual(responses[2]["result"]["structuredContent"]["kind"], "context_block")

    def test_content_length_serve_returns_parse_and_framing_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = MnemoMcpServer(state_dir=tmp)
            bad_json = b"{"
            recoverable_input = BytesIO(
                b"Content-Length: 1\r\n\r\n"
                + bad_json
                + _mcp_frame({"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
            )
            recoverable_output = BytesIO()

            server.serve_content_length(input_stream=recoverable_input, output_stream=recoverable_output)

            recoverable_responses = _read_mcp_frames(recoverable_output.getvalue())
            self.assertEqual(recoverable_responses[0]["error"]["code"], -32700)
            self.assertEqual(recoverable_responses[1]["id"], 9)
            self.assertIn("tools", recoverable_responses[1]["result"])

            framing_output = BytesIO()
            server.serve_content_length(
                input_stream=BytesIO(b"Content-Length: nope\r\n\r\n{}"),
                output_stream=framing_output,
            )
            framing_responses = _read_mcp_frames(framing_output.getvalue())
            self.assertEqual(len(framing_responses), 1)
            self.assertEqual(framing_responses[0]["error"]["code"], -32700)
            self.assertIn("Content-Length", framing_responses[0]["error"]["message"])


if __name__ == "__main__":
    unittest.main()
