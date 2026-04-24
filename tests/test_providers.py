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

    def test_anthropic_provider_remains_explicit_placeholder(self) -> None:
        with self.assertRaises(NotImplementedError):
            list(AnthropicProviderAdapter().stream(ProviderRunInput(messages=[], tools=[])))


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


class DaemonThreadingHTTPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False


if __name__ == "__main__":
    unittest.main()
