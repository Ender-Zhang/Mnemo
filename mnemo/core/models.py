from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RiskLevel = Literal["read", "write", "external", "admin"]
PromptMode = Literal["full", "minimal", "capsule", "none"]
RunStatus = Literal["running", "completed", "failed", "cancelled"]
MissionStatus = Literal["active", "paused", "completed", "cancelled", "archived"]
ChatEventType = Literal[
    "conversation.hydrated",
    "turn.started",
    "assistant.delta",
    "assistant.message",
    "status.updated",
    "action.queued",
    "action.started",
    "action.completed",
    "artifact.card",
    "decision.card",
    "recall.card",
    "learning.chip",
    "source.attached",
    "run.completed",
    "run.error",
]
PROMPT_MODES: tuple[PromptMode, ...] = ("full", "minimal", "capsule", "none")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: RiskLevel
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCallEnvelope:
    name: str
    arguments: dict[str, Any]
    call_id: str
    provider: str = "local"
    risk: RiskLevel = "read"
    source: str = "provider_native"


@dataclass(frozen=True)
class ToolPermission:
    allowed: bool
    risk: RiskLevel
    reason: str


@dataclass(frozen=True)
class ToolExecutionPolicy:
    allowed_risks: tuple[RiskLevel, ...] = ("read", "write")
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()

    def check(self, spec: "ToolSpec") -> ToolPermission:
        if spec.name in self.denied_tools:
            return ToolPermission(False, spec.risk, f"tool is denied by policy: {spec.name}")
        if self.allowed_tools and spec.name not in self.allowed_tools:
            return ToolPermission(False, spec.risk, f"tool is outside the allowed tool set: {spec.name}")
        if spec.risk not in self.allowed_risks:
            return ToolPermission(False, spec.risk, f"tool risk is not allowed: {spec.risk}")
        return ToolPermission(True, spec.risk, "allowed")


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    summary: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ChatEvent:
    event_id: str
    type: ChatEventType
    run_id: str
    conversation_id: str
    mission_id: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0


@dataclass(frozen=True)
class RunRequest:
    message: str
    state_dir: str
    conversation_id: str | None = None
    mission_id: str | None = None
    workspace_root: str | None = None
    prompt_mode: PromptMode = "full"


@dataclass(frozen=True)
class RunResult:
    conversation_id: str
    mission_id: str
    run_id: str
    response: str
    tool_results: list[ToolResult]
