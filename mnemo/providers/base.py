from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
import json
import socket
from typing import Any, Literal, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from ..core.errors import (
    ProviderConnectionError,
    ProviderPayloadError,
    ProviderStatusError,
    ProviderTimeoutError,
)
from ..core.models import ToolCallEnvelope, ToolSpec


ProviderEventType = Literal["text_delta", "tool_call", "completed"]


@dataclass(frozen=True)
class ProviderEvent:
    type: ProviderEventType
    text: str | None = None
    tool_call: ToolCallEnvelope | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_s: float = 30.0
    stream: bool = False


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

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def stream(self, request: ProviderRunInput) -> Iterable[ProviderEvent]:
        if self.config.stream:
            yield from self._stream_chat_completions(request)
            return
        payload = self._post_chat_completions(request)
        yield from self._events_from_payload(payload, request.tools)

    def _request_payload(self, request: ProviderRunInput, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": _normalize_chat_messages(request.messages),
            "stream": stream,
        }
        if request.tools:
            payload["tools"] = [_tool_spec_to_openai_tool(tool) for tool in request.tools]
        return payload

    def _request_headers(self, *, stream: bool) -> dict[str, str]:
        headers = {
            "Accept": "text/event-stream" if stream else "application/json",
            "Connection": "close",
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _post_chat_completions(self, request: ProviderRunInput) -> dict[str, Any]:
        http_request = urllib_request.Request(
            _chat_completions_url(self.config.base_url),
            data=json.dumps(self._request_payload(request, stream=False)).encode("utf-8"),
            headers=self._request_headers(stream=False),
            method="POST",
        )

        try:
            with urllib_request.urlopen(http_request, timeout=self.config.timeout_s) as response:
                response_body = response.read()
        except urllib_error.HTTPError as exc:
            raise ProviderStatusError(exc.code, _read_error_body(exc)) from exc
        except urllib_error.URLError as exc:
            if _is_timeout(exc.reason):
                raise ProviderTimeoutError("provider request timed out") from exc
            raise ProviderConnectionError("provider is unreachable") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderTimeoutError("provider request timed out") from exc
        except OSError as exc:
            raise ProviderConnectionError("provider is unreachable") from exc

        try:
            parsed = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderPayloadError("provider returned invalid JSON") from exc

        if not isinstance(parsed, dict):
            raise ProviderPayloadError("provider returned a non-object JSON payload")
        return parsed

    def _stream_chat_completions(self, request: ProviderRunInput) -> Iterable[ProviderEvent]:
        http_request = urllib_request.Request(
            _chat_completions_url(self.config.base_url),
            data=json.dumps(self._request_payload(request, stream=True)).encode("utf-8"),
            headers=self._request_headers(stream=True),
            method="POST",
        )

        risk_by_tool_name = {tool.name: tool.risk for tool in request.tools}
        tool_call_chunks: dict[int, dict[str, Any]] = {}
        last_payload: dict[str, Any] = {}
        last_choice: dict[str, Any] = {}

        try:
            with urllib_request.urlopen(http_request, timeout=self.config.timeout_s) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    payload = _loads_stream_chunk(data)
                    choice = _stream_choice(payload)
                    if choice is None:
                        continue
                    last_payload = payload
                    last_choice = choice
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict):
                        raise ProviderPayloadError("provider stream delta is not an object")

                    content = delta.get("content")
                    if content:
                        if not isinstance(content, str):
                            raise ProviderPayloadError("provider stream content is not a string")
                        yield ProviderEvent(type="text_delta", text=content)

                    _accumulate_stream_tool_calls(delta.get("tool_calls"), tool_call_chunks)
        except urllib_error.HTTPError as exc:
            raise ProviderStatusError(exc.code, _read_error_body(exc)) from exc
        except urllib_error.URLError as exc:
            if _is_timeout(exc.reason):
                raise ProviderTimeoutError("provider request timed out") from exc
            raise ProviderConnectionError("provider is unreachable") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderTimeoutError("provider request timed out") from exc
        except OSError as exc:
            raise ProviderConnectionError("provider is unreachable") from exc

        for tool_call in _parse_stream_tool_calls(tool_call_chunks, risk_by_tool_name, self.name):
            yield ProviderEvent(type="tool_call", tool_call=tool_call)
        yield ProviderEvent(type="completed", metadata=_completion_metadata(last_payload, last_choice, self.name))

    def _events_from_payload(self, payload: dict[str, Any], tools: Sequence[ToolSpec]) -> Iterable[ProviderEvent]:
        choice = _first_choice(payload)
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ProviderPayloadError("provider response missing choices[0].message")

        content = message.get("content")
        if content is not None:
            if not isinstance(content, str):
                raise ProviderPayloadError("provider response message content is not a string")
            if content:
                yield ProviderEvent(type="text_delta", text=content)

        risk_by_tool_name = {tool.name: tool.risk for tool in tools}
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            raise ProviderPayloadError("provider response message tool_calls is not a list")

        for tool_call in tool_calls:
            yield ProviderEvent(
                type="tool_call",
                tool_call=_parse_openai_tool_call(tool_call, risk_by_tool_name, self.name),
            )

        yield ProviderEvent(type="completed", metadata=_completion_metadata(payload, choice, self.name))


class AnthropicProviderAdapter:
    name = "anthropic"

    def stream(self, request: ProviderRunInput) -> Iterable[ProviderEvent]:
        raise NotImplementedError("Anthropic provider adapter will be implemented after the local harness stabilizes")


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _tool_spec_to_openai_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.input_schema,
        },
    }


def _read_error_body(error: urllib_error.HTTPError) -> str | None:
    try:
        body = error.read()
    except OSError:
        return None
    if not body:
        return None
    return body.decode("utf-8", errors="replace")


def _is_timeout(reason: Any) -> bool:
    return isinstance(reason, TimeoutError | socket.timeout)


def _first_choice(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderPayloadError("provider response missing choices")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProviderPayloadError("provider response choices[0] is not an object")
    return choice


def _loads_stream_chunk(data: str) -> dict[str, Any]:
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ProviderPayloadError("provider stream returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ProviderPayloadError("provider stream returned a non-object JSON payload")
    return parsed


def _stream_choice(payload: dict[str, Any]) -> dict[str, Any] | None:
    choices = payload.get("choices")
    if choices == []:
        return None
    if not isinstance(choices, list) or not choices:
        raise ProviderPayloadError("provider stream chunk missing choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProviderPayloadError("provider stream choices[0] is not an object")
    return choice


def _accumulate_stream_tool_calls(value: Any, chunks: dict[int, dict[str, Any]]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ProviderPayloadError("provider stream tool_calls is not a list")

    for item in value:
        if not isinstance(item, dict):
            raise ProviderPayloadError("provider stream tool call chunk is not an object")
        index = _stream_tool_call_index(item.get("index"), chunks)
        chunk = chunks.setdefault(index, {"id": "", "type": "function", "name": "", "arguments": ""})

        call_id = item.get("id")
        if isinstance(call_id, str) and call_id:
            chunk["id"] = call_id
        tool_type = item.get("type")
        if isinstance(tool_type, str) and tool_type:
            chunk["type"] = tool_type

        function = item.get("function") or {}
        if not isinstance(function, dict):
            raise ProviderPayloadError("provider stream tool call function is not an object")
        name = function.get("name")
        if isinstance(name, str) and name:
            chunk["name"] = name
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            chunk["arguments"] += arguments


def _stream_tool_call_index(value: Any, chunks: dict[int, dict[str, Any]]) -> int:
    if isinstance(value, int):
        return value
    if value is None:
        return len(chunks)
    raise ProviderPayloadError("provider stream tool call index is not an integer")


def _parse_stream_tool_calls(
    chunks: dict[int, dict[str, Any]],
    risk_by_tool_name: dict[str, str],
    provider_name: str,
) -> list[ToolCallEnvelope]:
    calls: list[ToolCallEnvelope] = []
    for index in sorted(chunks):
        chunk = chunks[index]
        calls.append(
            _parse_openai_tool_call(
                {
                    "id": chunk.get("id"),
                    "type": chunk.get("type") or "function",
                    "function": {
                        "name": chunk.get("name"),
                        "arguments": chunk.get("arguments") or "{}",
                    },
                },
                risk_by_tool_name,
                provider_name,
            )
        )
    return calls


def _parse_openai_tool_call(
    value: Any,
    risk_by_tool_name: dict[str, str],
    provider_name: str,
) -> ToolCallEnvelope:
    if not isinstance(value, dict):
        raise ProviderPayloadError("provider response tool call is not an object")

    call_id = value.get("id")
    if not isinstance(call_id, str) or not call_id:
        raise ProviderPayloadError("provider response tool call missing id")

    tool_type = value.get("type")
    if tool_type is not None and tool_type != "function":
        raise ProviderPayloadError("provider response tool call is not a function call")

    function = value.get("function")
    if not isinstance(function, dict):
        raise ProviderPayloadError("provider response tool call missing function")

    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise ProviderPayloadError("provider response tool call missing function name")

    arguments = _parse_tool_arguments(function.get("arguments", "{}"))
    return ToolCallEnvelope(
        name=name,
        arguments=arguments,
        call_id=call_id,
        provider=provider_name,
        risk=risk_by_tool_name.get(name, "read"),
    )


def _parse_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ProviderPayloadError("provider response tool call arguments must be JSON")

    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise ProviderPayloadError("provider response tool call arguments are invalid JSON") from exc

    if not isinstance(parsed, dict):
        raise ProviderPayloadError("provider response tool call arguments must decode to an object")
    return parsed


def _completion_metadata(payload: dict[str, Any], choice: dict[str, Any], provider_name: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"provider": provider_name}
    for key in ("id", "model", "created", "system_fingerprint"):
        if key in payload:
            metadata[key] = payload[key]
    if "finish_reason" in choice:
        metadata["finish_reason"] = choice["finish_reason"]
    usage = payload.get("usage")
    if isinstance(usage, dict):
        metadata["usage"] = usage
    return metadata


def _normalize_chat_messages(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        item = dict(message)
        if item.get("role") == "developer":
            item["role"] = "system"
        normalized.append(item)
    return normalized
