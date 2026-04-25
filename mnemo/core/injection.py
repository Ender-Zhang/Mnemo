from __future__ import annotations


def injection_warnings(value: str) -> list[str]:
    text = str(value or "").casefold()
    warnings: list[str] = []
    if any(marker in text for marker in PROMPT_OVERRIDE_MARKERS):
        warnings.append("possible_prompt_override")
    if any(marker in text for marker in SECRET_REQUEST_MARKERS):
        warnings.append("possible_secret_request")
    if any(marker in text for marker in TOOL_INJECTION_MARKERS):
        warnings.append("possible_tool_injection")
    return warnings


PROMPT_OVERRIDE_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "override system",
    "developer instructions",
    "system prompt",
)
SECRET_REQUEST_MARKERS = (
    "reveal hidden",
    "show hidden",
    "print secrets",
    "api key",
)
TOOL_INJECTION_MARKERS = (
    "<tool_call",
    "<function_call",
    "\"tool_calls\"",
    "call tool",
)
