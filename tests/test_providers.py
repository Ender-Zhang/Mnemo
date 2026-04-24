from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
from socketserver import ThreadingTCPServer
import threading
import unittest
from typing import Any

from mnemo.core.errors import ProviderPayloadError, ProviderStatusError, ProviderTimeoutError
from mnemo.core.models import ToolSpec
from mnemo.providers import AnthropicProviderAdapter, OpenAIProviderAdapter, ProviderConfig, ProviderRunInput


class ProviderAdapterTests(unittest.TestCase):
    def test_openai_provider_emits_text_and_completed_events(self) -> None:
        with FakeOpenAIServer(
            {
                "id": "chatcmpl_test",
                "model": "test-model",
                "choices": [{"message": {"content": "Hello from the provider"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            }
        ) as server:
            adapter = OpenAIProviderAdapter(
                ProviderConfig(base_url=server.base_url, model="test-model", api_key="test-key", timeout_s=1)
            )

            events = list(adapter.stream(ProviderRunInput(messages=[{"role": "user", "content": "Hi"}], tools=[])))

        self.assertEqual([event.type for event in events], ["text_delta", "completed"])
        self.assertEqual(events[0].text, "Hello from the provider")
        self.assertEqual(events[1].metadata["id"], "chatcmpl_test")
        self.assertEqual(events[1].metadata["finish_reason"], "stop")

        request = server.requests[0]
        self.assertEqual(request["path"], "/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(request["body"]["model"], "test-model")
        self.assertFalse(request["body"]["stream"])

    def test_openai_provider_sends_tool_specs_and_parses_tool_calls(self) -> None:
        tool = ToolSpec(
            name="memory_search",
            description="Search memory",
            risk="read",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
        with FakeOpenAIServer(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_123",
                                    "type": "function",
                                    "function": {
                                        "name": "memory_search",
                                        "arguments": json.dumps({"query": "direct answers"}),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        ) as server:
            adapter = OpenAIProviderAdapter(ProviderConfig(base_url=server.base_url, model="test-model"))

            events = list(adapter.stream(ProviderRunInput(messages=[{"role": "user", "content": "Search"}], tools=[tool])))

        self.assertEqual([event.type for event in events], ["tool_call", "completed"])
        self.assertIsNotNone(events[0].tool_call)
        self.assertEqual(events[0].tool_call.name, "memory_search")
        self.assertEqual(events[0].tool_call.arguments, {"query": "direct answers"})
        self.assertEqual(events[0].tool_call.call_id, "call_123")
        self.assertEqual(events[0].tool_call.provider, "openai")
        self.assertEqual(events[0].tool_call.risk, "read")

        sent_tool = server.requests[0]["body"]["tools"][0]
        self.assertEqual(sent_tool["type"], "function")
        self.assertEqual(sent_tool["function"]["name"], "memory_search")
        self.assertEqual(sent_tool["function"]["description"], "Search memory")
        self.assertEqual(sent_tool["function"]["parameters"], tool.input_schema)

    def test_openai_provider_parses_streamed_text_deltas(self) -> None:
        with FakeOpenAIStreamServer(
            [
                {"id": "chatcmpl_stream", "model": "test-model", "choices": [{"delta": {"content": "Hel"}}]},
                {
                    "id": "chatcmpl_stream",
                    "model": "test-model",
                    "choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}],
                },
            ]
        ) as server:
            adapter = OpenAIProviderAdapter(ProviderConfig(base_url=server.base_url, model="test-model", stream=True))

            events = list(adapter.stream(ProviderRunInput(messages=[{"role": "user", "content": "Hi"}], tools=[])))

        self.assertEqual([event.type for event in events], ["text_delta", "text_delta", "completed"])
        self.assertEqual([event.text for event in events[:2]], ["Hel", "lo"])
        self.assertEqual(events[-1].metadata["id"], "chatcmpl_stream")
        self.assertTrue(server.requests[0]["body"]["stream"])

    def test_openai_provider_parses_streamed_tool_call_chunks(self) -> None:
        tool = ToolSpec(
            name="memory_search",
            description="Search memory",
            risk="read",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        )
        with FakeOpenAIStreamServer(
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_stream",
                                        "type": "function",
                                        "function": {"name": "memory_search", "arguments": "{\"query\":"},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": " \"direct answers\"}"},
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            ]
        ) as server:
            adapter = OpenAIProviderAdapter(ProviderConfig(base_url=server.base_url, model="test-model", stream=True))

            events = list(adapter.stream(ProviderRunInput(messages=[{"role": "user", "content": "Search"}], tools=[tool])))

        self.assertEqual([event.type for event in events], ["tool_call", "completed"])
        self.assertEqual(events[0].tool_call.name, "memory_search")
        self.assertEqual(events[0].tool_call.arguments, {"query": "direct answers"})
        self.assertTrue(server.requests[0]["body"]["stream"])

    def test_openai_provider_raises_status_error(self) -> None:
        with FakeOpenAIServer({"error": {"message": "rate limited"}}, status=429) as server:
            adapter = OpenAIProviderAdapter(ProviderConfig(base_url=server.base_url, model="test-model"))

            with self.assertRaises(ProviderStatusError) as context:
                list(adapter.stream(ProviderRunInput(messages=[], tools=[])))

        self.assertEqual(context.exception.status_code, 429)
        self.assertIn("rate limited", context.exception.body or "")

    def test_openai_provider_raises_payload_error_for_bad_json(self) -> None:
        with FakeOpenAIServer(b"not-json") as server:
            adapter = OpenAIProviderAdapter(ProviderConfig(base_url=server.base_url, model="test-model"))

            with self.assertRaises(ProviderPayloadError):
                list(adapter.stream(ProviderRunInput(messages=[], tools=[])))

    def test_openai_provider_raises_timeout_error(self) -> None:
        with FakeOpenAIServer({"choices": [{"message": {"content": "too late"}}]}, delay_s=0.2) as server:
            adapter = OpenAIProviderAdapter(ProviderConfig(base_url=server.base_url, model="test-model", timeout_s=0.01))

            with self.assertRaises(ProviderTimeoutError):
                list(adapter.stream(ProviderRunInput(messages=[], tools=[])))

    def test_anthropic_provider_emits_text_and_sends_headers(self) -> None:
        with FakeAnthropicServer(
            {
                "id": "msg_test",
                "model": "claude-test",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello from Claude"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 4},
            }
        ) as server:
            adapter = AnthropicProviderAdapter(
                ProviderConfig(base_url=server.base_url, model="claude-test", api_key="test-key", timeout_s=1)
            )

            events = list(
                adapter.stream(
                    ProviderRunInput(
                        messages=[
                            {"role": "system", "content": "System rules"},
                            {"role": "developer", "content": "Developer rules"},
                            {"role": "user", "content": "Hi"},
                        ],
                        tools=[],
                    )
                )
            )

        self.assertEqual([event.type for event in events], ["text_delta", "completed"])
        self.assertEqual(events[0].text, "Hello from Claude")
        self.assertEqual(events[1].metadata["id"], "msg_test")
        self.assertEqual(events[1].metadata["stop_reason"], "end_turn")

        request = server.requests[0]
        self.assertEqual(request["path"], "/messages")
        self.assertEqual(request["headers"]["X-Api-Key"], "test-key")
        self.assertEqual(request["headers"]["Anthropic-Version"], "2023-06-01")
        self.assertEqual(request["body"]["model"], "claude-test")
        self.assertEqual(request["body"]["system"], "System rules\n\nDeveloper rules")
        self.assertEqual(request["body"]["messages"], [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}])
        self.assertFalse(request["body"]["stream"])

    def test_anthropic_provider_sends_tools_and_parses_tool_use(self) -> None:
        tool = ToolSpec(
            name="memory_search",
            description="Search memory",
            risk="read",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        )
        with FakeAnthropicServer(
            {
                "id": "msg_tool",
                "model": "claude-test",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "memory_search",
                        "input": {"query": "direct answers"},
                    }
                ],
                "stop_reason": "tool_use",
            }
        ) as server:
            adapter = AnthropicProviderAdapter(ProviderConfig(base_url=server.base_url, model="claude-test"))

            events = list(adapter.stream(ProviderRunInput(messages=[{"role": "user", "content": "Search"}], tools=[tool])))

        self.assertEqual([event.type for event in events], ["tool_call", "completed"])
        self.assertEqual(events[0].tool_call.name, "memory_search")
        self.assertEqual(events[0].tool_call.arguments, {"query": "direct answers"})
        self.assertEqual(events[0].tool_call.call_id, "toolu_123")
        self.assertEqual(events[0].tool_call.provider, "anthropic")
        self.assertEqual(events[0].tool_call.risk, "read")
        self.assertEqual(server.requests[0]["body"]["tools"][0]["name"], "memory_search")
        self.assertEqual(server.requests[0]["body"]["tools"][0]["input_schema"], tool.input_schema)

    def test_anthropic_provider_normalizes_tool_result_messages(self) -> None:
        with FakeAnthropicServer(
            {
                "id": "msg_result",
                "model": "claude-test",
                "role": "assistant",
                "content": [{"type": "text", "text": "Done"}],
            }
        ) as server:
            adapter = AnthropicProviderAdapter(ProviderConfig(base_url=server.base_url, model="claude-test"))

            list(
                adapter.stream(
                    ProviderRunInput(
                        messages=[
                            {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "toolu_123",
                                        "type": "function",
                                        "function": {"name": "memory_search", "arguments": json.dumps({"query": "x"})},
                                    }
                                ],
                            },
                            {"role": "tool", "tool_call_id": "toolu_123", "content": "{\"matches\":[]}"},
                        ],
                        tools=[],
                    )
                )
            )

        self.assertEqual(
            server.requests[0]["body"]["messages"],
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "toolu_123", "name": "memory_search", "input": {"query": "x"}}
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_123", "content": "{\"matches\":[]}"}
                    ],
                },
            ],
        )

    def test_anthropic_provider_parses_streamed_text_and_tool_use(self) -> None:
        tool = ToolSpec(
            name="memory_search",
            description="Search memory",
            risk="read",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        )
        with FakeAnthropicStreamServer(
            [
                {"type": "message_start", "message": {"id": "msg_stream", "model": "claude-test", "role": "assistant"}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "tool_use", "id": "toolu_stream", "name": "memory_search", "input": {}},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": "{\"query\":"},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": " \"direct answers\"}"},
                },
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
                {"type": "message_stop"},
            ]
        ) as server:
            adapter = AnthropicProviderAdapter(
                ProviderConfig(base_url=server.base_url, model="claude-test", stream=True)
            )

            events = list(adapter.stream(ProviderRunInput(messages=[{"role": "user", "content": "Search"}], tools=[tool])))

        self.assertEqual([event.type for event in events], ["text_delta", "text_delta", "tool_call", "completed"])
        self.assertEqual([event.text for event in events[:2]], ["Hel", "lo"])
        self.assertEqual(events[2].tool_call.call_id, "toolu_stream")
        self.assertEqual(events[2].tool_call.arguments, {"query": "direct answers"})
        self.assertEqual(events[-1].metadata["stop_reason"], "tool_use")
        self.assertTrue(server.requests[0]["body"]["stream"])

    def test_anthropic_provider_raises_status_and_payload_errors(self) -> None:
        with FakeAnthropicServer({"error": {"message": "rate limited"}}, status=429) as server:
            adapter = AnthropicProviderAdapter(ProviderConfig(base_url=server.base_url, model="claude-test"))

            with self.assertRaises(ProviderStatusError) as context:
                list(adapter.stream(ProviderRunInput(messages=[], tools=[])))

        self.assertEqual(context.exception.status_code, 429)
        self.assertIn("rate limited", context.exception.body or "")

        with FakeAnthropicServer(b"not-json") as server:
            adapter = AnthropicProviderAdapter(ProviderConfig(base_url=server.base_url, model="claude-test"))

            with self.assertRaises(ProviderPayloadError):
                list(adapter.stream(ProviderRunInput(messages=[], tools=[])))


class FakeOpenAIServer:
    def __init__(self, response: dict[str, Any] | bytes, status: int = 200, delay_s: float = 0.0) -> None:
        self.response = response
        self.status = status
        self.delay_s = delay_s
        self.requests: list[dict[str, Any]] = []
        self._server = DaemonThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeOpenAIServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if fake_server.delay_s:
                    import time

                    time.sleep(fake_server.delay_s)
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                fake_server.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": json.loads(raw_body.decode("utf-8")),
                    }
                )

                response_body = (
                    fake_server.response
                    if isinstance(fake_server.response, bytes)
                    else json.dumps(fake_server.response).encode("utf-8")
                )
                self.send_response(fake_server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(response_body)
                    self.wfile.flush()
                except BrokenPipeError:
                    pass
                self.close_connection = True

            def log_message(self, format: str, *args: Any) -> None:
                return None

        return Handler


class FakeOpenAIStreamServer:
    def __init__(self, chunks: list[dict[str, Any]], status: int = 200) -> None:
        self.chunks = chunks
        self.status = status
        self.requests: list[dict[str, Any]] = []
        self._server = DaemonThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeOpenAIStreamServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                fake_server.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": json.loads(raw_body.decode("utf-8")),
                    }
                )

                response_body = b"".join(
                    f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
                    for chunk in fake_server.chunks
                ) + b"data: [DONE]\n\n"
                self.send_response(fake_server.status)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(response_body)
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, format: str, *args: Any) -> None:
                return None

        return Handler


class FakeAnthropicServer:
    def __init__(self, response: dict[str, Any] | bytes, status: int = 200) -> None:
        self.response = response
        self.status = status
        self.requests: list[dict[str, Any]] = []
        self._server = DaemonThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeAnthropicServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                fake_server.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": json.loads(raw_body.decode("utf-8")),
                    }
                )
                response_body = (
                    fake_server.response
                    if isinstance(fake_server.response, bytes)
                    else json.dumps(fake_server.response).encode("utf-8")
                )
                self.send_response(fake_server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(response_body)
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, format: str, *args: Any) -> None:
                return None

        return Handler


class FakeAnthropicStreamServer:
    def __init__(self, chunks: list[dict[str, Any]], status: int = 200) -> None:
        self.chunks = chunks
        self.status = status
        self.requests: list[dict[str, Any]] = []
        self._server = DaemonThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeAnthropicStreamServer:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                fake_server.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": json.loads(raw_body.decode("utf-8")),
                    }
                )
                response_body = b"".join(
                    f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
                    for chunk in fake_server.chunks
                )
                self.send_response(fake_server.status)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(response_body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(response_body)
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, format: str, *args: Any) -> None:
                return None

        return Handler


class DaemonThreadingHTTPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False


if __name__ == "__main__":
    unittest.main()
