from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error, request

from ..core.config import MemoryConfig
from ..core.jsonutil import dumps
from ..core.log import get_logger, log_event

_LOG = get_logger("provider")


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
        allowed_tools = plan.get("allowed_tools") if isinstance(plan.get("allowed_tools"), list) else []
        allowed_tool_text = ", ".join(str(tool) for tool in allowed_tools if tool) or (
            "memory_promote_candidate, memory_reject_candidate, memory_tombstone, memory_decay_stale_pages"
        )
        advanced_note = (
            " Advanced Dreaming is enabled. You may propose memory_link_pages for additive links. "
            "For memory_rewrite_page, memory_merge_pages, memory_split_page, and memory_reconcile_conflict, "
            "return them only when the after state is clear; the service will store them as pending operator proposals."
            if plan.get("advanced_dreaming")
            else ""
        )
        goal_note = (
            " Goal tools are full-auto. Use goal_apply_proposal or goal_reject_proposal for pending goal proposals, "
            "and goal_create, goal_update, goal_complete, goal_cancel, or goal_archive for direct plan item maintenance. "
            "Use the exact uid/scope from the delta and include a concise reason on every goal action."
            if any(str(tool).startswith("goal_") for tool in allowed_tools)
            else ""
        )
        payload = _chat_payload(
            self.config,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a memory maintenance planner. Return JSON only with an actions array. "
                        f"Allowed tools: {allowed_tool_text}. "
                        "Do not reject user-provided private profile/contact facts solely because they are private; "
                        "promote them when stable and useful. "
                        "Reject or forget private content only when the user asked not to save it, asked to delete it, "
                        "or the source is unsafe/untrusted. "
                        "Include a concise reason on every promote or reject action."
                        f"{advanced_note}"
                        f"{goal_note}"
                    ),
                },
                {
                    "role": "user",
                    "content": dumps({"delta": delta, "plan": plan}),
                },
            ],
        )
        response = self._post_json("/chat/completions", payload)
        parsed = _parse_message_json_object(response)
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
                        "facts, observations, and plan_proposals arrays. Facts are durable user preferences, "
                        "identity, boundaries, project context, or standing aspirations/goals (who the user is "
                        "or wants to be long-term) — use the 'goals' dimension for those. Plan proposals are only "
                        "concrete, actionable todos, follow-ups, reminders, or time-bound intended work; do NOT turn "
                        "a vague aspiration or a stated preference into a plan proposal. Observations are task-local or uncertain context. "
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
                            "plan_proposal_schema": {
                                "kind": "goal|todo",
                                "title": "short user-visible plan title",
                                "detail": "optional supporting detail",
                                "scope": "memory scope",
                                "priority": "low|normal|high",
                                "due_at": "optional unix timestamp when explicit",
                                "confidence": "0.0-1.0",
                                "reason": "concise extraction reason",
                            },
                        }
                    ),
                },
            ],
        )
        response = self._post_json("/chat/completions", payload)
        parsed = _parse_message_json_object(response)
        return parsed if isinstance(parsed, dict) else {}

    def reconcile_conflict(self, *, candidate: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
        """Decide how a new claim and a conflicting stable memory should reconcile.

        Returns JSON: {resolution: keep_new|keep_old|keep_both|merge,
        merged_content?, rationale?}. ``merge`` lets the model rewrite the page
        with a single disambiguated / supplemented statement.
        """
        payload = _chat_payload(
            self.config,
            [
                {
                    "role": "system",
                    "content": (
                        "You reconcile a new memory claim against an existing, conflicting stable memory. "
                        "Return JSON only: {\"resolution\": one of keep_new|keep_old|keep_both|merge, "
                        "\"merged_content\": string (required when resolution is merge), \"rationale\": short string}. "
                        "Choose keep_new when the new claim supersedes the old (e.g. a changed preference); "
                        "keep_old when the new claim is wrong or weaker; keep_both when both are independently true; "
                        "merge when one disambiguated or time-qualified statement captures both — then write that "
                        "statement in merged_content (concise, first person about the user)."
                    ),
                },
                {
                    "role": "user",
                    "content": dumps({
                        "new_claim": {
                            "claim": candidate.get("claim"),
                            "dimension": candidate.get("dimension"),
                            "confidence": candidate.get("confidence"),
                            "scope": candidate.get("scope"),
                        },
                        "existing_memory": {
                            "title": page.get("title"),
                            "content": page.get("content"),
                            "confidence": page.get("confidence"),
                            "scope": page.get("scope"),
                        },
                    }),
                },
            ],
        )
        response = self._post_json("/chat/completions", payload)
        parsed = _parse_message_json_object(response)
        return parsed if isinstance(parsed, dict) else {}

    def consolidate_page(self, *, page: dict[str, Any], facts: list[str]) -> str | None:
        """Rewrite an accumulated memory page into a concise, non-redundant form.

        Preserves every distinct fact, merges overlapping ones, drops repetition.
        Returns the consolidated body text (plain lines), or None on failure.
        """
        payload = _chat_payload(
            self.config,
            [
                {
                    "role": "system",
                    "content": (
                        "You consolidate one long-term memory page about a user. Remove exact and redundant "
                        "duplicates and tidy the ordering, but KEEP EACH DISTINCT FACT'S ORIGINAL WORDING "
                        "verbatim — do not paraphrase, shorten, or drop any fact. A downstream check rejects "
                        "your output if any input fact no longer appears in it. Return JSON only: "
                        "{\"content\": string (one fact per line, original wording, no bullet characters), "
                        "\"rationale\": short string}."
                    ),
                },
                {
                    "role": "user",
                    "content": dumps({
                        "title": page.get("title"),
                        "dimension": (page.get("metadata") or {}).get("dimension") if isinstance(page.get("metadata"), dict) else None,
                        "facts": facts,
                    }),
                },
            ],
        )
        response = self._post_json("/chat/completions", payload)
        parsed = _parse_message_json_object(response)
        content = parsed.get("content") if isinstance(parsed, dict) else None
        text = str(content or "").strip()
        return text or None

    def ping(self) -> dict[str, Any]:
        """Minimal request to verify the chat endpoint is reachable and authorized."""
        payload = _chat_payload(self.config, [{"role": "user", "content": "ping"}])
        payload["max_tokens"] = 1
        return self._post_json("/chat/completions", payload)

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
            log_event(_LOG, "provider_error", level=logging.WARNING, path=path, model=self.config.model, status=exc.code, detail=detail[:240])
            raise ValueError(f"maintenance provider error {exc.code}: {detail[:240]}") from exc
        except OSError as exc:
            log_event(_LOG, "provider_error", level=logging.WARNING, path=path, model=self.config.model, error=str(exc))
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


def _parse_message_json_object(response: dict[str, Any]) -> dict[str, Any]:
    errors: list[Exception] = []
    for content in _message_text_candidates(response):
        try:
            return _parse_json_object(content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(exc)
    if errors:
        raise ValueError("maintenance provider returned no parseable JSON object") from errors[0]
    return {}


def _message_text_candidates(response: dict[str, Any]) -> list[str]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return []
    first = choices[0]
    if not isinstance(first, dict):
        return []
    message = first.get("message")
    if not isinstance(message, dict):
        return []
    candidates: list[str] = []
    for key in ("content", "reasoning", "reasoning_content", "thinking"):
        candidates.extend(_text_values(message.get(key)))
    return _dedupe_texts(candidates)


def _text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_text_values(item))
        return result
    if isinstance(value, dict):
        result: list[str] = []
        for key in ("text", "content", "reasoning", "reasoning_content", "thinking"):
            result.extend(_text_values(value.get(key)))
        return result
    return []


def _dedupe_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _parse_json_object(content: str) -> dict[str, Any]:
    text = _strip_json_fence(str(content or "").strip())
    if not text:
        return {}
    parsed = _load_json_object(text)
    if parsed is None:
        parsed = _load_json_object(_extract_first_json_object(text))
    if parsed is None:
        raise ValueError("maintenance provider returned no parseable JSON object")
    return parsed


def _strip_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    stripped = text.strip("`").strip()
    if stripped.startswith("json"):
        return stripped[4:].strip()
    return stripped


def _load_json_object(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _extract_first_json_object(text: str) -> str | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            _parsed, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return text[index : index + end]
    return None
