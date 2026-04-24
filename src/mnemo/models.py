from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RiskLevel = Literal["read", "write", "external", "admin"]
RunStatus = Literal["running", "completed", "failed"]
MissionStatus = Literal["active", "paused", "completed", "cancelled", "archived"]


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
class ToolResult:
    call_id: str
    name: str
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class RunRequest:
    message: str
    state_dir: str
    conversation_id: str | None = None
    mission_id: str | None = None


@dataclass(frozen=True)
class RunResult:
    conversation_id: str
    mission_id: str
    run_id: str
    response: str
    tool_results: list[ToolResult]
