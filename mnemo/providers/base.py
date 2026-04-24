from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ..core.models import ToolCallEnvelope, ToolSpec


ProviderEventType = Literal["text_delta", "tool_call", "completed"]


@dataclass(frozen=True)
class ProviderEvent:
    type: ProviderEventType
    text: str | None = None
    tool_call: ToolCallEnvelope | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderRunInput:
    messages: Sequence[dict[str, Any]]
    tools: Sequence[ToolSpec]
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    name: str

    def stream(self, request: ProviderRunInput) -> Iterable[ProviderEvent]:
        """Yield provider-native model/tool events normalized at Mnemo's boundary."""


class OpenAIProviderAdapter:
    name = "openai"

    def stream(self, request: ProviderRunInput) -> Iterable[ProviderEvent]:
        raise NotImplementedError("OpenAI provider adapter will be implemented after the local harness stabilizes")


class AnthropicProviderAdapter:
    name = "anthropic"

    def stream(self, request: ProviderRunInput) -> Iterable[ProviderEvent]:
        raise NotImplementedError("Anthropic provider adapter will be implemented after the local harness stabilizes")
