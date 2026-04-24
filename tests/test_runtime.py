from __future__ import annotations

import tempfile
import unittest

from mnemo.core.models import RunRequest, ToolCallEnvelope
from mnemo.providers import ProviderEvent
from mnemo.runtime import ProviderAgentRuntime, run_local, stream_local
from mnemo.storage import StateStore


class LocalRuntimeTests(unittest.TestCase):
    def test_remember_creates_candidate_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_local(RunRequest(message="remember: I prefer concise updates", state_dir=tmp))

            self.assertEqual(result.tool_results[0].name, "memory_write_candidate")
            self.assertTrue(result.tool_results[0].ok)
            self.assertIn("记忆候选", result.response)

            store = StateStore(tmp)
            matches = store.search_memory_candidates("concise")
            events = store.get_run_events(result.run_id)

            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["claim"], "I prefer concise updates")
            self.assertIn("tool.called", [event["event_type"] for event in events])
            self.assertIn("run.completed", [event["event_type"] for event in events])

    def test_followup_reuses_active_mission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = run_local(RunRequest(message="remember: Use direct answers", state_dir=tmp))
            second = run_local(
                RunRequest(
                    message="search: direct answers",
                    state_dir=tmp,
                    conversation_id=first.conversation_id,
                )
            )

            self.assertEqual(first.conversation_id, second.conversation_id)
            self.assertEqual(first.mission_id, second.mission_id)
            self.assertEqual(second.tool_results[0].name, "memory_search")
            self.assertEqual(len(second.tool_results[0].result["matches"]), 1)

    def test_streaming_events_include_actions_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events = list(stream_local(RunRequest(message="remember: stream actions", state_dir=tmp)))
            event_types = [event.type for event in events]

            self.assertIn("turn.started", event_types)
            self.assertIn("action.queued", event_types)
            self.assertIn("action.started", event_types)
            self.assertIn("action.completed", event_types)
            self.assertIn("learning.chip", event_types)
            self.assertEqual(event_types[-1], "run.completed")

            store = StateStore(tmp)
            ledger_events = store.get_run_events(events[-1].run_id)
            self.assertIn("chat.event", [event["event_type"] for event in ledger_events])
            self.assertEqual(events[-1].data["result"]["tool_results"][0]["name"], "memory_write_candidate")

    def test_provider_runtime_streams_text_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider([[ProviderEvent(type="text_delta", text="Hello from model"), ProviderEvent(type="completed")]])
            events = list(ProviderAgentRuntime(provider).stream(RunRequest(message="hello", state_dir=tmp)))

            event_types = [event.type for event in events]
            self.assertIn("assistant.delta", event_types)
            self.assertEqual(events[-1].type, "run.completed")
            self.assertEqual(events[-1].data["result"]["response"], "Hello from model")
            self.assertEqual(provider.requests[0].messages[-1]["content"], "hello")

    def test_provider_runtime_executes_tool_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider(
                [
                    [
                        ProviderEvent(
                            type="tool_call",
                            tool_call=ToolCallEnvelope(
                                name="memory_write_candidate",
                                arguments={"claim": "User likes tool loops"},
                                call_id="call_fake",
                                provider="fake",
                                risk="write",
                            ),
                        ),
                        ProviderEvent(type="completed"),
                    ],
                    [ProviderEvent(type="text_delta", text="Recorded."), ProviderEvent(type="completed")],
                ]
            )
            events = list(ProviderAgentRuntime(provider).stream(RunRequest(message="remember via model", state_dir=tmp)))
            event_types = [event.type for event in events]

            self.assertIn("action.queued", event_types)
            self.assertIn("action.completed", event_types)
            self.assertIn("learning.chip", event_types)
            self.assertEqual(events[-1].data["result"]["response"], "Recorded.")
            self.assertEqual(len(provider.requests), 2)
            self.assertEqual(provider.requests[1].messages[-1]["role"], "tool")


class FakeProvider:
    name = "fake"

    def __init__(self, rounds: list[list[ProviderEvent]]) -> None:
        self.rounds = rounds
        self.requests = []

    def stream(self, request):
        self.requests.append(request)
        if not self.rounds:
            return [ProviderEvent(type="completed")]
        return self.rounds.pop(0)


if __name__ == "__main__":
    unittest.main()
