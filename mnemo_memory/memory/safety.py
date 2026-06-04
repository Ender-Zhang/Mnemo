from __future__ import annotations

from typing import Any

from ..core.injection import injection_warnings


def scan_memory_candidate(claim: str, evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    evidence_items = [item for item in evidence or [] if isinstance(item, dict)]
    sources = _taint_sources(evidence_items)
    warnings = _warning_items("claim", claim)
    for index, item in enumerate(evidence_items):
        source = _evidence_source(item)
        for warning in _warning_items(f"evidence[{index}]", _evidence_text(item)):
            warning["source"] = source
            warnings.append(warning)

    taint = _taint_level(sources)
    has_injection = bool(warnings)
    has_external_taint = any(source["taint"] == "external" for source in sources)
    requires_review = has_injection
    risk = "high" if has_injection else "medium" if has_external_taint else "low"
    return {
        "kind": "memory_safety",
        "taint": taint,
        "risk": risk,
        "requires_review": requires_review,
        "review_reason": "prompt_injection" if requires_review else None,
        "sources": sources or [{"source": "unspecified", "taint": "trusted"}],
        "warnings": warnings[:10],
    }


def append_safety_evidence(evidence: list[dict[str, Any]] | None, scan: dict[str, Any]) -> list[dict[str, Any]]:
    items = [item for item in evidence or [] if isinstance(item, dict)]
    return [*items, scan]


def _taint_sources(evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for item in evidence:
        source = _evidence_source(item)
        taint = _source_taint(source)
        key = (source, taint)
        if key in seen:
            continue
        seen.add(key)
        result.append({"source": source, "taint": taint})
    return result


def _evidence_source(item: dict[str, Any]) -> str:
    for key in ("source", "tool_name", "kind", "provider", "source_type"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if item.get("url"):
        return "web_fetch"
    if item.get("path"):
        return "file"
    return "unspecified"


def _source_taint(source: str) -> str:
    normalized = source.casefold()
    if normalized in _TRUSTED_SOURCES or any(marker in normalized for marker in _TRUSTED_MARKERS):
        return "trusted"
    if normalized in _EXTERNAL_SOURCES or any(marker in normalized for marker in _EXTERNAL_MARKERS):
        return "external"
    return "unknown"


def _warning_items(location: str, value: str) -> list[dict[str, str]]:
    return [
        {"kind": warning, "location": location}
        for warning in injection_warnings(value)
    ]


def _evidence_text(item: dict[str, Any]) -> str:
    fields: list[str] = []
    for key in ("text", "content", "quote", "snippet", "output", "body", "summary", "error"):
        value = item.get(key)
        if isinstance(value, str):
            fields.append(value)
    return "\n".join(fields)


def _taint_level(sources: list[dict[str, str]]) -> str:
    levels = {source["taint"] for source in sources}
    if "external" in levels:
        return "external"
    if "unknown" in levels:
        return "unknown"
    return "trusted"


_TRUSTED_SOURCES = {
    "user",
    "user_message",
    "run.input",
    "run.output",
    "working_note",
    "manual",
    "cli",
    "web",
}
_TRUSTED_MARKERS = (
    "user",
    "run:",
    "mission:",
)
_EXTERNAL_SOURCES = {
    "web_fetch",
    "http",
    "browser",
    "file_read",
    "file_search",
    "shell_exec",
    "tool_result",
    "imported_skill",
    "mcp",
    "external_runtime",
}
_EXTERNAL_MARKERS = (
    "web_fetch",
    "http://",
    "https://",
    "file",
    "shell",
    "tool_result",
    "imported",
    "mcp",
    "external",
)
