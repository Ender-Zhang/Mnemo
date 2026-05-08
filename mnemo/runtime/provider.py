from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ..core.config import DEFAULT_MAX_TOOL_ROUNDS
from ..core.errors import MnemoError
from ..core.models import ChatEvent, RunRequest, RunResult, ToolExecutionPolicy, ToolResult
from ..memory import MemoryEngine
from ..providers import ProviderAdapter, ProviderRunInput, provider_capabilities_for_adapter
from ..prompt import PromptAssembler, load_prompt_bootstrap
from ..skills import SkillService, default_skill_roots
from ..storage import StateStore
from ..tools import ToolHarness, ToolRegistry, compact_tool_result, tool_specs_as_json_schema
from .common import (
    action_card,
    build_tool_bundle,
    cancellation_result,
    ensure_executable_prompt_mode,
    expand_tool_bundle_from_result,
    make_chat_event_emitter,
    project_tool_result,
    result_as_dict,
    run_result_from_dict,
    tool_result_card,
    tool_result_summary,
)
from .learning import (
    build_learning_debt_packet,
    build_learning_packet,
    build_learning_tool_bundle,
    learning_reflection_messages,
    should_reflect_on_learning_packet,
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
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        enable_learning_reflection: bool = True,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_tool_rounds = max(1, min(int(max_tool_rounds), 64))
        self.enable_learning_reflection = enable_learning_reflection

    def run(self, request: RunRequest) -> RunResult:
        final_result: RunResult | None = None
        for event in self.stream(request):
            if event.type == "run.completed":
                final_result = run_result_from_dict(event.data["result"])
        if final_result is None:
            raise MnemoError("run did not produce a completion event")
        return final_result

    def stream(self, request: RunRequest) -> Iterator[ChatEvent]:
        ensure_executable_prompt_mode(request.prompt_mode)
        store = StateStore(request.state_dir)
        store.initialize()
        ledger = RunLedger(store)
        registry = self.registry or ToolRegistry.from_store(store)
        if self.registry is not None:
            registry.load_generated_tools(store.list_generated_tools(status="active", limit=100))

        conversation_id = resolve_conversation(store, request, title=_short_title(request.message))
        mission_id = resolve_mission(store, conversation_id, request, brief=_short_title(request.message, limit=120))
        run_id = store.create_run(conversation_id, mission_id, request.message)
        capabilities = provider_capabilities_for_adapter(self.provider)
        active_tool_bundle = build_tool_bundle(registry, prompt_mode=request.prompt_mode, capabilities=capabilities)
        active_cache_plan = capabilities.cache_plan(active_tool_bundle.metadata())
        harness = ToolHarness(
            store=store,
            ledger=ledger,
            registry=registry,
            policy=ToolExecutionPolicy(allowed_tools=active_tool_bundle.tool_names),
            workspace_root=request.workspace_root,
        )
        emit = make_chat_event_emitter(
            ledger=ledger,
            run_id=run_id,
            conversation_id=conversation_id,
            mission_id=mission_id,
        )
        mission = store.get_mission(mission_id) or {}
        memory_engine = MemoryEngine(store)
        bootstrap = load_prompt_bootstrap(request.state_dir, workspace_root=request.workspace_root)
        assembled_prompt = PromptAssembler().assemble(
            request.message,
            mission=mission,
            tool_specs=active_tool_bundle.specs,
            soul_context=bootstrap.soul,
            workspace_context=bootstrap.workspace,
            memory_snapshot=memory_engine.load_or_compile_l1_snapshot(),
            memory_cards=memory_engine.context_cards(request.message, limit=5),
            skill_cards=SkillService(store, roots=default_skill_roots(request.state_dir)).context_cards(limit=12),
            mode=request.prompt_mode,
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
                "tool_bundle": active_tool_bundle.metadata(),
                "provider_capabilities": capabilities.metadata(),
                "cache_plan": active_cache_plan,
                "tool_count": len(active_tool_bundle.tool_names),
                "tools": [spec["name"] for spec in tool_specs_as_json_schema(list(active_tool_bundle.specs))],
                "provider": self.provider.name,
            },
        )
        yield emit("status.updated", {"text": "正在调用模型。", "tone": "working"})

        messages = assembled_prompt.messages()
        response_parts: list[str] = []
        tool_results: list[ToolResult] = []

        try:
            for tool_round in range(self.max_tool_rounds + 1):
                tool_calls = []
                completed = []
                assistant_parts: list[str] = []
                for provider_event in self.provider.stream(
                    ProviderRunInput(
                        messages=messages,
                        tools=active_tool_bundle.specs,
                        metadata={
                            "run_id": run_id,
                            "tool_round": tool_round,
                            "tool_bundle": active_tool_bundle.metadata(),
                            "provider_capabilities": capabilities.metadata(),
                            "cache_plan": active_cache_plan,
                        },
                    )
                ):
                    if provider_event.type == "text_delta" and provider_event.text:
                        assistant_parts.append(provider_event.text)
                        response_parts.append(provider_event.text)
                        yield emit("assistant.delta", {"text": provider_event.text})
                    elif provider_event.type == "tool_call" and provider_event.tool_call:
                        tool_calls.append(provider_event.tool_call)
                    elif provider_event.type == "completed":
                        completed.append(provider_event)

                assistant_text = "".join(assistant_parts)

                if store.is_run_cancelled(run_id):
                    yield from cancellation_result(
                        store=store,
                        ledger=ledger,
                        emit=emit,
                        run_id=run_id,
                        conversation_id=conversation_id,
                        mission_id=mission_id,
                        tool_results=tool_results,
                    )
                    return

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
                    if store.is_run_cancelled(run_id):
                        yield from cancellation_result(
                            store=store,
                            ledger=ledger,
                            emit=emit,
                            run_id=run_id,
                            conversation_id=conversation_id,
                            mission_id=mission_id,
                            tool_results=tool_results,
                        )
                        return
                    action = action_card(registry, call)
                    yield emit("action.queued", {"action": action, "provider_call_id": call.call_id})
                    yield emit("action.started", {"action": action})
                    result = harness.execute(call, run_id=run_id, mission_id=mission_id)
                    tool_results.append(result)
                    expanded_bundle = expand_tool_bundle_from_result(registry, active_tool_bundle, result)
                    if expanded_bundle is not None:
                        active_tool_bundle = expanded_bundle
                        active_cache_plan = capabilities.cache_plan(active_tool_bundle.metadata())
                        harness.policy = ToolExecutionPolicy(allowed_tools=active_tool_bundle.tool_names)
                        ledger.append(
                            run_id,
                            "tool_bundle.expanded",
                            {
                                "tool_bundle": active_tool_bundle.metadata(),
                                "cache_plan": active_cache_plan,
                                "call_id": call.call_id,
                            },
                        )
                    yield emit(
                        "action.completed",
                        {
                            "action_id": call.call_id,
                            "outcome": "success" if result.ok else "failed",
                            "summary": tool_result_summary(result),
                            "tool_name": result.name,
                            "result": tool_result_card(result),
                        },
                    )
                    for projected in project_tool_result(result, emit):
                        yield projected
                    if store.is_run_cancelled(run_id):
                        yield from cancellation_result(
                            store=store,
                            ledger=ledger,
                            emit=emit,
                            run_id=run_id,
                            conversation_id=conversation_id,
                            mission_id=mission_id,
                            tool_results=tool_results,
                        )
                        return
                    messages.append(_tool_result_message(result))

                if tool_round >= self.max_tool_rounds:
                    ledger.append(
                        run_id,
                        "provider.tool_budget_exhausted",
                        {
                            "provider": self.provider.name,
                            "tool_round": tool_round,
                            "tool_call_count": len(tool_calls),
                        },
                    )
                    yield emit("status.updated", {"text": "工具轮次已用完，正在整理现有结果。", "tone": "working"})
                    messages.append(
                        {
                            "role": "developer",
                            "content": (
                                "Tool budget is exhausted for this turn. Do not request more tools. "
                                "Answer directly using the available context and tool results, and note uncertainty "
                                "briefly if the evidence is incomplete."
                            ),
                        }
                    )
                    completed = []
                    for provider_event in self.provider.stream(
                        ProviderRunInput(
                            messages=messages,
                            tools=(),
                            metadata={
                                "run_id": run_id,
                                "tool_round": tool_round + 1,
                                "tool_budget_exhausted": True,
                                "tool_bundle": active_tool_bundle.metadata(),
                                "provider_capabilities": capabilities.metadata(),
                                "cache_plan": active_cache_plan,
                            },
                        )
                    ):
                        if provider_event.type == "text_delta" and provider_event.text:
                            response_parts.append(provider_event.text)
                            yield emit("assistant.delta", {"text": provider_event.text})
                        elif provider_event.type == "tool_call":
                            ledger.append(
                                run_id,
                                "provider.tool_call_ignored",
                                {
                                    "provider": self.provider.name,
                                    "reason": "tool_budget_exhausted",
                                },
                            )
                        elif provider_event.type == "completed":
                            completed.append(provider_event)

                    ledger.append(
                        run_id,
                        "provider.completed",
                        {
                            "provider": self.provider.name,
                            "tool_round": tool_round + 1,
                            "metadata": [event.metadata for event in completed],
                            "tool_call_count": 0,
                            "tool_budget_exhausted": True,
                        },
                    )
                    break

            response = _final_response_text(response_parts, tool_results)
            checkpoint = _checkpoint(store, mission_id, request.message, response, run_id, tool_results)
            store.update_mission_checkpoint(mission_id, checkpoint)
            yield emit("assistant.message", {"text": response, "final": True})
            ledger.append(run_id, "assistant.response", {"text": response})
            store.complete_run(run_id, response)
            if not store.is_run_cancelled(run_id):
                yield from self._stream_learning_reflection(
                    request=request,
                    store=store,
                    ledger=ledger,
                    registry=registry,
                    run_id=run_id,
                    mission_id=mission_id,
                    response=response,
                    tool_results=tool_results,
                    capabilities=capabilities,
                    base_epoch=active_tool_bundle.epoch,
                    emit=emit,
                )
            ledger.append(run_id, "run.completed", {"status": "completed"})
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

    def _stream_learning_reflection(
        self,
        *,
        request: RunRequest,
        store: StateStore,
        ledger: RunLedger,
        registry: ToolRegistry,
        run_id: str,
        mission_id: str,
        response: str,
        tool_results: list[ToolResult],
        capabilities: Any,
        base_epoch: int,
        emit,
    ) -> Iterator[ChatEvent]:
        packet = build_learning_packet(store, run_id, response=response, tool_results=tool_results)
        ledger.append(run_id, "learning.packet", {"packet": packet, "mode": "provider_reflection"})
        if not self.enable_learning_reflection:
            ledger.append(run_id, "learning.reflection.skipped", {"reason": "disabled"})
            return
        if request.prompt_mode != "full":
            ledger.append(run_id, "learning.reflection.skipped", {"reason": "prompt_mode", "mode": request.prompt_mode})
            return
        should_reflect, reason = should_reflect_on_learning_packet(packet)
        if not should_reflect:
            ledger.append(run_id, "learning.reflection.skipped", {"reason": reason})
            debt_packet, debt_reason = build_learning_debt_packet(store, run_id)
            if debt_packet is None:
                ledger.append(run_id, "learning.debt_review.skipped", {"reason": debt_reason})
                return
            ledger.append(run_id, "learning.debt_review.packet", {"packet": debt_packet, "reason": debt_reason})
            yield from self._stream_learning_packet_reflection(
                request=request,
                store=store,
                ledger=ledger,
                registry=registry,
                run_id=run_id,
                mission_id=mission_id,
                packet=debt_packet,
                tool_results=tool_results,
                capabilities=capabilities,
                base_epoch=base_epoch,
                emit=emit,
                stage="learning_debt_review",
                status_text="正在回看最近几轮是否有可学习信号。",
            )
            return

        yield from self._stream_learning_packet_reflection(
            request=request,
            store=store,
            ledger=ledger,
            registry=registry,
            run_id=run_id,
            mission_id=mission_id,
            packet=packet,
            tool_results=tool_results,
            capabilities=capabilities,
            base_epoch=base_epoch,
            emit=emit,
            stage="after_turn_learning",
            status_text="正在整理可学习信号。",
        )

    def _stream_learning_packet_reflection(
        self,
        *,
        request: RunRequest,
        store: StateStore,
        ledger: RunLedger,
        registry: ToolRegistry,
        run_id: str,
        mission_id: str,
        packet: dict[str, Any],
        tool_results: list[ToolResult],
        capabilities: Any,
        base_epoch: int,
        emit,
        stage: str,
        status_text: str,
    ) -> Iterator[ChatEvent]:
        bundle = build_learning_tool_bundle(
            registry,
            provider_adapter_version=capabilities.adapter_version,
            epoch=base_epoch + 1,
        )
        cache_plan = capabilities.cache_plan(bundle.metadata())
        packet_kind = str(packet.get("kind") or "learning_packet")
        ledger.append(
            run_id,
            "learning.reflection.started",
            {"tool_bundle": bundle.metadata(), "cache_plan": cache_plan, "stage": stage, "packet_kind": packet_kind},
        )
        if stage == "learning_debt_review":
            ledger.append(run_id, "learning.debt_review.started", {"packet_kind": packet_kind})
        yield emit("status.updated", {"text": status_text, "tone": "learning"})

        tool_calls = []
        completed = []
        assistant_parts: list[str] = []
        try:
            for provider_event in self.provider.stream(
                ProviderRunInput(
                    messages=learning_reflection_messages(packet),
                    tools=bundle.specs,
                    metadata={
                        "run_id": run_id,
                        "stage": stage,
                        "tool_bundle": bundle.metadata(),
                        "provider_capabilities": capabilities.metadata(),
                        "cache_plan": cache_plan,
                        "packet_kind": packet_kind,
                    },
                )
            ):
                if provider_event.type == "text_delta" and provider_event.text:
                    assistant_parts.append(provider_event.text)
                elif provider_event.type == "tool_call" and provider_event.tool_call:
                    tool_calls.append(provider_event.tool_call)
                elif provider_event.type == "completed":
                    completed.append(provider_event)
        except Exception as exc:
            ledger.append(run_id, "learning.reflection.failed", {"error": str(exc), "phase": "provider"})
            yield emit("status.updated", {"text": "学习整理暂时跳过。", "tone": "warning"})
            return

        ledger.append(
            run_id,
            "learning.reflection.provider_completed",
            {
                "stage": stage,
                "packet_kind": packet_kind,
                "metadata": [event.metadata for event in completed],
                "tool_call_count": len(tool_calls),
                "assistant_text": "".join(assistant_parts).strip()[:500],
            },
        )
        if not tool_calls:
            ledger.append(run_id, "learning.reflection.completed", {"tool_call_count": 0, "tool_results": []})
            if stage == "learning_debt_review":
                ledger.append(run_id, "learning.debt_review.completed", {"tool_call_count": 0})
            return

        reflection_harness = ToolHarness(
            store=store,
            ledger=ledger,
            registry=registry,
            policy=ToolExecutionPolicy(allowed_tools=bundle.tool_names),
            workspace_root=request.workspace_root,
        )
        learning_results: list[dict[str, Any]] = []
        for call in tool_calls:
            if store.is_run_cancelled(run_id):
                ledger.append(run_id, "learning.reflection.skipped", {"reason": "cancelled"})
                return
            try:
                action = action_card(registry, call)
            except Exception as exc:
                ledger.append(
                    run_id,
                    "learning.reflection.tool_skipped",
                    {"call_id": call.call_id, "tool_name": call.name, "error": str(exc)},
                )
                continue
            learning_event_meta = {"internal": "learning", "stage": stage}
            yield emit("action.queued", {"action": action, "provider_call_id": call.call_id, **learning_event_meta})
            yield emit("action.started", {"action": action, **learning_event_meta})
            result = reflection_harness.execute(call, run_id=run_id, mission_id=mission_id)
            tool_results.append(result)
            learning_results.append({"name": result.name, "ok": result.ok, "summary": tool_result_summary(result)})
            yield emit(
                "action.completed",
                {
                    "action_id": call.call_id,
                    "outcome": "success" if result.ok else "failed",
                    "summary": tool_result_summary(result),
                    "tool_name": result.name,
                    "result": tool_result_card(result),
                    **learning_event_meta,
                },
            )
            for projected in project_tool_result(result, emit):
                yield projected
        ledger.append(
            run_id,
            "learning.reflection.completed",
            {
                "stage": stage,
                "packet_kind": packet_kind,
                "tool_call_count": len(tool_calls),
                "tool_results": learning_results,
            },
        )
        if stage == "learning_debt_review":
            ledger.append(
                run_id,
                "learning.debt_review.completed",
                {"tool_call_count": len(tool_calls), "tool_results": learning_results},
            )


def run_provider(
    request: RunRequest,
    provider: ProviderAdapter,
    *,
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
) -> RunResult:
    return ProviderAgentRuntime(provider, max_tool_rounds=max_tool_rounds).run(request)


def stream_provider(
    request: RunRequest,
    provider: ProviderAdapter,
    *,
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
) -> Iterator[ChatEvent]:
    return ProviderAgentRuntime(provider, max_tool_rounds=max_tool_rounds).stream(request)


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


def _final_response_text(response_parts: list[str], tool_results: list[ToolResult]) -> str:
    response = "".join(response_parts).strip()
    if response and not _looks_like_unexecuted_tool_call(response):
        return response
    if not response:
        return "已完成。"
    summaries = [
        f"- {result.name}: {result.summary or ('ok' if result.ok else result.error or 'failed')}"
        for result in tool_results[-5:]
    ]
    if not summaries:
        return "工具轮次已用完，模型仍尝试继续调用工具；本轮没有可整理的工具结果。"
    return "工具轮次已用完，模型仍尝试继续调用工具。我已停止继续调用，当前已有结果：\n" + "\n".join(summaries)


def _looks_like_unexecuted_tool_call(response: str) -> bool:
    stripped = response.strip().casefold()
    if stripped.startswith("<tool_call") and "</tool_call>" in stripped:
        return True
    if stripped.startswith("<function=") or stripped.startswith("<function "):
        return True
    if stripped.startswith('{"tool_calls"') or stripped.startswith('{"tool_call"'):
        return True
    return False


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
