from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mnemo.core.errors import MnemoError
from mnemo.core.models import RunRequest, ToolCallEnvelope
from mnemo.memory import MemoryEngine
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

    def test_local_recall_projects_recall_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("runtime recall")
            mission_id = store.create_mission(conversation_id, "runtime recall")
            seed_run_id = store.create_run(conversation_id, mission_id, "Zephyr runtime handoff")
            store.complete_run(seed_run_id, "Zephyr handoff can be continued.")
            store.upsert_memory_page("knowledge: zephyr", "Zephyr needs concise handoff notes", confidence=0.9)
            store.upsert_artifact(mission_id, seed_run_id, "Zephyr handoff draft", "Zephyr artifact body")
            store.add_inbox_item(category="decision", title="Approve Zephyr handoff", source_run_id=seed_run_id)

            events = list(
                stream_local(
                    RunRequest(message="recall: Zephyr", state_dir=tmp, conversation_id=conversation_id)
                )
            )

            event_types = [event.type for event in events]
            recall_event = next(event for event in events if event.type == "recall.card")
            result = events[-1].data["result"]
            self.assertIn("recall.card", event_types)
            self.assertEqual(result["tool_results"][0]["name"], "recall_search")
            self.assertGreaterEqual(recall_event.data["recall"]["count"], 4)
            self.assertEqual(recall_event.data["recall"]["query"], "Zephyr")

    def test_provider_runtime_streams_text_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider([[ProviderEvent(type="text_delta", text="Hello from model"), ProviderEvent(type="completed")]])
            events = list(ProviderAgentRuntime(provider).stream(RunRequest(message="hello", state_dir=tmp)))

            event_types = [event.type for event in events]
            self.assertIn("assistant.delta", event_types)
            self.assertEqual(events[-1].type, "run.completed")
            self.assertEqual(events[-1].data["result"]["response"], "Hello from model")
            self.assertEqual(provider.requests[0].messages[-1]["content"], "hello")
            self.assertEqual(
                [message["role"] for message in provider.requests[0].messages],
                ["system", "developer", "developer", "developer", "user"],
            )
            self.assertEqual(provider.requests[0].metadata["provider_capabilities"]["provider"], "fake")
            self.assertEqual(provider.requests[0].metadata["cache_plan"]["tool_bundle"]["epoch"], 1)

            store = StateStore(tmp)
            prompt_event = next(
                event for event in store.get_run_events(events[-1].run_id) if event["event_type"] == "prompt.assembled"
            )
            self.assertEqual(prompt_event["payload"]["provider_capabilities"]["provider"], "fake")
            self.assertEqual(prompt_event["payload"]["cache_plan"]["tool_bundle"]["epoch"], 1)

    def test_runtime_rejects_none_prompt_mode_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MnemoError):
                list(stream_local(RunRequest(message="hello", state_dir=tmp, prompt_mode="none")))

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

    def test_provider_runtime_adds_progressive_memory_and_skill_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("context")
            mission_id = store.create_mission(conversation_id, "context tests")
            seed_run_id = store.create_run(conversation_id, mission_id, "seed")
            store.add_memory_candidate(seed_run_id, "User prefers concise writing", confidence=0.8)
            store.upsert_memory_page(
                "preferences: writing",
                "User prefers concise writing in project updates",
                confidence=0.9,
            )
            MemoryEngine(store).compile_l1_snapshot()
            store.upsert_skill("writer", "Draft concise prose", "Full skill body", status="active")
            provider = FakeProvider([[ProviderEvent(type="text_delta", text="Ready"), ProviderEvent(type="completed")]])

            list(
                ProviderAgentRuntime(provider).stream(
                    RunRequest(message="concise writing", state_dir=tmp, conversation_id=conversation_id)
                )
            )

            prompt_text = "\n".join(message["content"] for message in provider.requests[0].messages)
            self.assertIn("Daily compiled memory snapshot", prompt_text)
            self.assertIn("Relevant memory index", prompt_text)
            self.assertIn("User prefers concise writing", prompt_text)
            self.assertIn("Available skill index", prompt_text)
            self.assertIn("writer [active]", prompt_text)
            self.assertNotIn("Full skill body", prompt_text)

    def test_provider_runtime_minimal_prompt_mode_limits_disclosure_and_write_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            workspace = root / "workspace"
            state_dir.mkdir()
            workspace.mkdir()
            (state_dir / "SOUL.md").write_text("User likes private runtime answers.", encoding="utf-8")
            (workspace / "AGENTS.md").write_text("Minimal workspace context.", encoding="utf-8")
            (workspace / "MEMORY.md").write_text("Legacy memory dump.", encoding="utf-8")
            store = StateStore(str(state_dir))
            store.initialize()
            conversation_id = store.create_conversation("minimal prompt")
            mission_id = store.create_mission(conversation_id, "minimal prompt")
            seed_run_id = store.create_run(conversation_id, mission_id, "seed")
            store.add_memory_candidate(seed_run_id, "User prefers private detail", confidence=0.8)
            store.upsert_memory_page("preferences: private", "User prefers private detail", confidence=0.9)
            MemoryEngine(store).compile_l1_snapshot()
            store.upsert_skill("private_writer", "Draft private prose", "Full private skill body", status="active")
            provider = FakeProvider([[ProviderEvent(type="text_delta", text="Ready"), ProviderEvent(type="completed")]])

            events = list(
                ProviderAgentRuntime(provider).stream(
                    RunRequest(
                        message="private detail",
                        state_dir=str(state_dir),
                        conversation_id=conversation_id,
                        workspace_root=str(workspace),
                        prompt_mode="minimal",
                    )
                )
            )

            prompt_text = "\n".join(message["content"] for message in provider.requests[0].messages)
            tool_names = [tool.name for tool in provider.requests[0].tools]
            prompt_event = next(
                event for event in store.get_run_events(events[-1].run_id) if event["event_type"] == "prompt.assembled"
            )
            block_ids = [block["id"] for block in prompt_event["payload"]["blocks"]]

            self.assertIn("Minimal workspace context.", prompt_text)
            self.assertNotIn("User likes private runtime answers.", prompt_text)
            self.assertNotIn("Daily compiled memory snapshot", prompt_text)
            self.assertNotIn("Available skill index", prompt_text)
            self.assertNotIn("Legacy memory dump.", prompt_text)
            self.assertIn("memory_search", tool_names)
            self.assertIn("tool_search", tool_names)
            self.assertIn("tool_expand_schema", tool_names)
            self.assertNotIn("memory_write_candidate", tool_names)
            self.assertNotIn("skill_propose_candidate", tool_names)
            self.assertEqual(prompt_event["payload"]["mode"], "minimal")
            self.assertEqual(prompt_event["payload"]["tool_bundle"]["profile"], "minimal.v1")
            self.assertEqual(prompt_event["payload"]["tool_bundle"]["tool_count"], len(tool_names))
            self.assertIn("workspace.bootstrap.agents_md", block_ids)
            self.assertNotIn("soul.user_contract", block_ids)
            self.assertNotIn("memory.index", block_ids)
            self.assertNotIn("skills.index", block_ids)

    def test_provider_runtime_expands_tool_bundle_after_model_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider(
                [
                    [
                        ProviderEvent(
                            type="tool_call",
                            tool_call=ToolCallEnvelope(
                                name="tool_expand_schema",
                                arguments={"names": ["memory_write_candidate"]},
                                call_id="call_expand",
                                provider="fake",
                                risk="read",
                            ),
                        ),
                        ProviderEvent(type="completed"),
                    ],
                    [ProviderEvent(type="text_delta", text="Expanded."), ProviderEvent(type="completed")],
                ]
            )

            events = list(
                ProviderAgentRuntime(provider).stream(
                    RunRequest(message="expand tools", state_dir=tmp, prompt_mode="minimal")
                )
            )

            first_tool_names = [tool.name for tool in provider.requests[0].tools]
            second_tool_names = [tool.name for tool in provider.requests[1].tools]
            store = StateStore(tmp)
            expanded_event = next(
                event for event in store.get_run_events(events[-1].run_id) if event["event_type"] == "tool_bundle.expanded"
            )

            self.assertNotIn("memory_write_candidate", first_tool_names)
            self.assertIn("memory_write_candidate", second_tool_names)
            self.assertEqual(provider.requests[1].metadata["tool_bundle"]["epoch"], 2)
            self.assertEqual(provider.requests[1].metadata["cache_plan"]["tool_bundle"]["epoch"], 2)
            self.assertEqual(
                expanded_event["payload"]["tool_bundle"]["cache_bust_reason"],
                "lazy_schema_expansion",
            )
            self.assertEqual(expanded_event["payload"]["cache_plan"]["tool_bundle"]["epoch"], 2)

    def test_provider_runtime_adds_soul_and_workspace_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            workspace = root / "workspace"
            state_dir.mkdir()
            workspace.mkdir()
            (state_dir / "SOUL.md").write_text("User likes direct runtime answers.", encoding="utf-8")
            (workspace / "AGENTS.md").write_text("Project context: use bootstrap path.", encoding="utf-8")
            provider = FakeProvider([[ProviderEvent(type="text_delta", text="Ready"), ProviderEvent(type="completed")]])

            events = list(
                ProviderAgentRuntime(provider).stream(
                    RunRequest(message="hello", state_dir=str(state_dir), workspace_root=str(workspace))
                )
            )

            prompt_text = "\n".join(message["content"] for message in provider.requests[0].messages)
            self.assertIn("User likes direct runtime answers.", prompt_text)
            self.assertIn("Project context: use bootstrap path.", prompt_text)

            store = StateStore(str(state_dir))
            prompt_event = next(
                event for event in store.get_run_events(events[-1].run_id) if event["event_type"] == "prompt.assembled"
            )
            blocks = {block["id"]: block for block in prompt_event["payload"]["blocks"]}
            self.assertIn("soul.user_contract", blocks)
            self.assertIn("workspace.bootstrap.agents_md", blocks)
            self.assertEqual(blocks["soul.user_contract"]["cache_segment"], "user_profile")
            self.assertEqual(blocks["workspace.bootstrap.agents_md"]["metadata"]["path"], "AGENTS.md")
            self.assertNotIn("Project context: use bootstrap path.", str(prompt_event["payload"]))

    def test_provider_runtime_exposes_active_generated_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("generated tools")
            mission_id = store.create_mission(conversation_id, "generated tool prompt")
            run_id = store.create_run(conversation_id, mission_id, "seed")
            candidate_id = store.add_tool_candidate(
                run_id,
                "lookup_memory",
                {
                    "name": "lookup_memory",
                    "description": "Lookup memory with a focused argument name",
                    "risk": "read",
                    "input_schema": {
                        "type": "object",
                        "properties": {"term": {"type": "string"}},
                        "required": ["term"],
                        "additionalProperties": False,
                    },
                    "implementation": {
                        "type": "alias",
                        "target_tool": "memory_search",
                        "argument_map": {"query": {"from": "term"}},
                    },
                },
            )
            store.upsert_generated_tool(
                candidate_id=candidate_id,
                name="lookup_memory",
                description="Lookup memory with a focused argument name",
                risk="read",
                input_schema={
                    "type": "object",
                    "properties": {"term": {"type": "string"}},
                    "required": ["term"],
                    "additionalProperties": False,
                },
                implementation={
                    "type": "alias",
                    "target_tool": "memory_search",
                    "argument_map": {"query": {"from": "term"}},
                },
            )
            provider = FakeProvider([[ProviderEvent(type="text_delta", text="Ready"), ProviderEvent(type="completed")]])

            list(
                ProviderAgentRuntime(provider).stream(
                    RunRequest(message="use generated tools", state_dir=tmp, conversation_id=conversation_id)
                )
            )

            tool_names = [tool.name for tool in provider.requests[0].tools]
            self.assertIn("lookup_memory", tool_names)

    def test_provider_runtime_completes_cancelled_when_signal_is_observed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = CancellingProvider(tmp)

            events = list(ProviderAgentRuntime(provider).stream(RunRequest(message="cancel me", state_dir=tmp)))

            completed = events[-1]
            store = StateStore(tmp)
            self.assertEqual(completed.type, "run.completed")
            self.assertEqual(completed.data["status"], "cancelled")
            self.assertEqual(store.get_run(completed.run_id)["status"], "cancelled")
            self.assertEqual(completed.data["result"]["response"], "已取消。")


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


class CancellingProvider:
    name = "fake"

    def __init__(self, state_dir: str) -> None:
        self.state_dir = state_dir

    def stream(self, request):
        StateStore(self.state_dir).cancel_run(request.metadata["run_id"], reason="test cancellation")
        return [ProviderEvent(type="completed")]


if __name__ == "__main__":
    unittest.main()
