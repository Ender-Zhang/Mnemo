from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from ..core.config import MemoryConfig
from ..core.jsonutil import dumps


class OpenAICompatibleMemoryMaintainer:
    def __init__(self, config: MemoryConfig) -> None:
        if config.provider != "openai-compatible":
            raise ValueError("mnemo-memory v1 only supports openai-compatible maintenance providers")
        if not config.base_url:
            raise ValueError("OpenAI-compatible maintenance requires base_url")
        if not config.model:
            raise ValueError("OpenAI-compatible maintenance requires model")
        self.config = config

    def propose_actions(self, *, delta: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
        payload = _chat_payload(
            self.config,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a memory maintenance planner. Return JSON only with an actions array. "
                        "Allowed tools: memory_promote_candidate, memory_reject_candidate, "
                        "memory_tombstone, memory_decay_stale_pages."
                    ),
                },
                {
                    "role": "user",
                    "content": dumps({"delta": delta, "plan": plan}),
                },
            ],
        )
        response = self._post_json("/chat/completions", payload)
        content = _message_content(response)
        parsed = _parse_json_object(content)
        actions = parsed.get("actions") if isinstance(parsed, dict) else None
        if not isinstance(actions, list):
            return []
        return [action for action in actions if isinstance(action, dict)]

    def extract_event_memory(self, *, event: dict[str, Any], context: list[dict[str, Any]]) -> dict[str, Any]:
        payload = _chat_payload(
            self.config,
            [
                {
                    "role": "system",
                    "content": (
                        "You classify one conversation event for long-term memory. Return JSON only with "
                        "facts and observations arrays. Facts are durable user preferences, identity, goals, "
                        "boundaries, or project context. Observations are task-local or uncertain context. "
                        "Do not infer a durable preference from a single slot-filling answer such as a coffee "
                        "choice unless the user explicitly says it is a default, habit, usual preference, or "
                        "future instruction."
                    ),
                },
                {
                    "role": "user",
                    "content": dumps(
                        {
                            "event": event,
                            "context": context,
                            "fact_schema": {
                                "claim": "durable claim text",
                                "dimension": "preferences|identity|goals|boundaries|context|history|patterns",
                                "scope": "memory scope",
                                "confidence": "0.0-1.0",
                            },
                            "observation_schema": {
                                "content": "task-local context",
                                "retention": "ephemeral|memory_candidate",
                                "dimension": "context",
                                "scope": "memory scope",
                            },
                        }
                    ),
                },
            ],
        )
        response = self._post_json("/chat/completions", payload)
        parsed = _parse_json_object(_message_content(response))
        return parsed if isinstance(parsed, dict) else {}

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = str(self.config.base_url or "").rstrip("/")
        req = request.Request(
            base + path,
            data=dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}),
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_s) as resp:
                body = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"maintenance provider error {exc.code}: {detail[:240]}") from exc
        except OSError as exc:
            raise ValueError(f"maintenance provider request failed: {exc}") from exc
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("maintenance provider returned non-object JSON")
        return parsed


def _chat_payload(config: MemoryConfig, messages: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": 0,
    }
    if config.thinking_enabled:
        payload["thinking"] = {"type": "enabled"}
    return payload


def _message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "")


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    parsed = json.loads(text or "{}")
    if not isinstance(parsed, dict):
        return {}
    return parsed
