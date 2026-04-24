from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ..core.errors import MnemoError
from ..core.models import ChatEvent, RunRequest, RunResult, ToolResult
from ..memory import MemoryEngine
from ..providers import ProviderAdapter, ProviderRunInput
from ..prompt import PromptAssembler
from ..skills import SkillService, default_skill_roots
from ..storage import StateStore
from ..tools import ToolHarness, ToolRegistry, compact_tool_result, tool_specs_as_json_schema
from .common import (
    action_card,
    make_chat_event_emitter,
    project_tool_result,
    result_as_dict,
    run_result_from_dict,
    tool_result_summary,
)
from .ledger import RunLedger
from .local import _short_title
from .state import resolve_conversation, resolve_mission


class ProviderAgentRuntime:
    def __init__(
        self,
        provider: ProviderAdapter,
        *,
        registry: ToolRegistry | None = None,
        max_tool_rounds: int = 3,
    ) -> None:
        self.provider = provider
        self.registry = registry or ToolRegistry()
        self.max_tool_rounds = max_tool_rounds

    def run(self, request: RunRequest) -> RunResult:
        final_result: RunResult | None = None
        for event in self.stream(request):
            if event.type == "run.completed":
                final_result = run_result_from_dict(event.data["result"])
        if final_result is None:
            raise MnemoError("run did not produce a completion event")
        return final_result

    def stream(self, request: RunRequest) -> Iterator[ChatEvent]:
        store = StateStore(request.state_dir)
        store.initialize()
        ledger = RunLedger(store)
        harness = ToolHarness(store=store, ledger=ledger, registry=self.registry)

        conversation_id = resolve_conversation(store, request, title=_short_title(request.message))
        mission_id = resolve_mission(store, conversation_id, request, brief=_short_title(request.message, limit=120))
        run_id = store.create_run(conversation_id, mission_id, request.message)
        emit = make_chat_event_emitter(
            ledger=ledger,
            run_id=run_id,
            conversation_id=conversation_id,
            mission_id=mission_id,
        )
        mission = store.get_mission(mission_id) or {}
        assembled_prompt = PromptAssembler().assemble(
            request.message,
            mission=mission,
            tool_specs=self.registry.specs(),
            memory_cards=MemoryEngine(store).context_cards(request.message, limit=5),
            skill_cards=SkillService(store, roots=default_skill_roots(request.state_dir)).context_cards(limit=12),
        )

        ledger.append(
            run_id,
            "request.received",
            {
                "conversation_id": conversation_id,
                "mission_id": mission_id,
                "message": request.message,
                "source": "cli",
                "runtime": "provider",
                "provider": self.provider.name,
            },
        )
        yield emit(
            "turn.started",
            {
                "turn_id": run_id,
                "input_summary": _short_title(request.message, limit=100),
            },
        )
        yield emit("conversation.hydrated", {"summary": "已恢复当前对话和任务状态。"})
        ledger.append(
            run_id,
            "prompt.assembled",
            {
                **assembled_prompt.metadata(),
                "mode": "full",
                "tool_count": len(self.registry.specs()),
                "tools": [spec["name"] for spec in tool_specs_as_json_schema(self.registry.specs())],
                "provider": self.provider.name,
            },
        )
        yield emit("status.updated", {"text": "正在调用模型。", "tone": "working"})

        messages = assembled_prompt.messages()
        response_parts: list[str] = []
        tool_results: list[ToolResult] = []

        try:
            for tool_round in range(self.max_tool_rounds + 1):
                provider_events = list(
                    self.provider.stream(
                        ProviderRunInput(
                            messages=messages,
                            tools=self.registry.specs(),
                            metadata={"run_id": run_id, "tool_round": tool_round},
                        )
                    )
                )
                tool_calls = [event.tool_call for event in provider_events if event.type == "tool_call" and event.tool_call]
                assistant_text = "".join(event.text or "" for event in provider_events if event.type == "text_delta")
                completed = [event for event in provider_events if event.type == "completed"]

                if assistant_text:
                    response_parts.append(assistant_text)
                    yield emit("assistant.delta", {"text": assistant_text})

                ledger.append(
                    run_id,
                    "provider.completed",
                    {
                        "provider": self.provider.name,
                        "tool_round": tool_round,
                        "metadata": [event.metadata for event in completed],
                        "tool_call_count": len(tool_calls),
                    },
                )

                if not tool_calls:
                    break

                messages.append(_assistant_tool_call_message(tool_calls, assistant_text))
                for call in tool_calls:
                    action = action_card(self.registry, call)
                    yield emit("action.queued", {"action": action, "provider_call_id": call.call_id})
                    yield emit("action.started", {"action": action})
                    result = harness.execute(call, run_id=run_id, mission_id=mission_id)
                    tool_results.append(result)
                    yield emit(
                        "action.completed",
                        {
                            "action_id": call.call_id,
                            "outcome": "success" if result.ok else "failed",
                            "summary": tool_result_summary(result),
                            "tool_name": result.name,
                        },
                    )
                    for projected in project_tool_result(result, emit):
                        yield projected
                    messages.append(_tool_result_message(result))
            else:
                raise MnemoError("provider exceeded maximum tool rounds")

            response = "".join(response_parts).strip() or "已完成。"
            checkpoint = _checkpoint(store, mission_id, request.message, response, run_id, tool_results)
            store.update_mission_checkpoint(mission_id, checkpoint)
            yield emit("assistant.message", {"text": response, "final": True})
            ledger.append(run_id, "assistant.response", {"text": response})
            ledger.append(run_id, "run.completed", {"status": "completed"})
            store.complete_run(run_id, response)
            result = RunResult(
                conversation_id=conversation_id,
                mission_id=mission_id,
                run_id=run_id,
                response=response,
                tool_results=tool_results,
            )
            yield emit("run.completed", {"status": "completed", "result": result_as_dict(result)})
        except Exception as exc:
            response = f"Run failed: {exc}"
            yield emit("run.error", {"error": str(exc), "provider": self.provider.name})
            ledger.append(run_id, "run.completed", {"status": "failed", "error": str(exc)})
            store.complete_run(run_id, response, status="failed")
            raise


def run_provider(request: RunRequest, provider: ProviderAdapter) -> RunResult:
    return ProviderAgentRuntime(provider).run(request)


def stream_provider(request: RunRequest, provider: ProviderAdapter) -> Iterator[ChatEvent]:
    return ProviderAgentRuntime(provider).stream(request)


def _assistant_tool_call_message(tool_calls: list[Any], content: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": _json_dumps(call.arguments),
                },
            }
            for call in tool_calls
        ],
    }


def _tool_result_message(result: ToolResult) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": result.call_id,
        "content": _json_dumps(compact_tool_result(result)),
    }


def _checkpoint(
    store: StateStore,
    mission_id: str,
    user_message: str,
    response: str,
    run_id: str,
    tool_results: list[ToolResult],
) -> dict[str, Any]:
    mission = store.get_mission(mission_id) or {}
    checkpoint = dict(mission.get("checkpoint") or {})
    checkpoint.update(
        {
            "goal": mission.get("brief") or _short_title(user_message, limit=120),
            "status": "active",
            "last_user_message": user_message,
            "last_response": response,
            "last_run_id": run_id,
            "last_tools": [
                {
                    "name": result.name,
                    "ok": result.ok,
                    "result": result.result,
                    "error": result.error,
                }
                for result in tool_results
            ],
        }
    )
    return checkpoint


def _json_dumps(value: Any) -> str:
    from ..core.jsonutil import dumps

    return dumps(value)
