from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from .constants import MEMORY_SEARCH_SCOPES, _NEGATIVE_MARKERS, _POSITIVE_MARKERS, _STOPWORDS

def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _non_negative_float(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None or parsed < 0:
        return None
    return parsed

def _metadata_timestamp(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    number_value = _float_or_none(text)
    if number_value is not None:
        return number_value
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()

def _bounded_confidence(value: Any, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return min(1.0, max(0.0, confidence))

def _fingerprint(value: str) -> str:
    return re.sub(r"\W+", "", value.casefold())

def _keywords(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    return [
        token
        for token in tokens
        if len(token) > 2 and token not in _STOPWORDS
    ]

def _polarity(value: str) -> str:
    text = f" {_normalize_space(value).casefold()} "
    if any(marker in text for marker in _NEGATIVE_MARKERS):
        return "negative"
    if any(marker in text for marker in _POSITIVE_MARKERS):
        return "positive"
    return "neutral"

def _is_conflict(left: str, right: str) -> bool:
    left_polarity = _polarity(left)
    right_polarity = _polarity(right)
    if {left_polarity, right_polarity} != {"positive", "negative"}:
        return False
    left_keywords = set(_keywords(left))
    right_keywords = set(_keywords(right))
    return bool(left_keywords & right_keywords)

def _normalize_space(value: str) -> str:
    return " ".join(value.strip().split())

def _normalize_search_scope(value: str) -> str:
    normalized = str(value or "memory").strip().casefold()
    if normalized not in MEMORY_SEARCH_SCOPES:
        raise ValueError(f"invalid memory search scope: {value}")
    if normalized == "stable":
        return "memory"
    return normalized

def _normalize_tombstone_target_type(value: str) -> str:
    normalized = str(value or "auto").strip().casefold()
    if normalized not in {"auto", "candidate", "page"}:
        raise ValueError(f"invalid memory tombstone target type: {value}")
    return normalized

def _curation_status(reason: str) -> str:
    slug = _status_reason(reason)
    if slug == "low_usefulness":
        return "archived:low_usefulness"
    return f"tombstoned:{slug}"

def _is_harmful_reason(reason: str) -> bool:
    return _status_reason(reason) == "harmful"

def _compact_safety_scan(scan: dict[str, Any]) -> dict[str, Any]:
    return {
        "taint": scan.get("taint"),
        "risk": scan.get("risk"),
        "requires_review": bool(scan.get("requires_review")),
        "review_reason": scan.get("review_reason"),
        "sources": scan.get("sources", [])[:6],
        "warnings": scan.get("warnings", [])[:6],
    }

def _is_stale_status(status: Any) -> bool:
    normalized = str(status or "").casefold()
    return normalized.startswith("stale") or normalized.startswith("archived") or "stale" in normalized

def _is_tombstone_status(status: Any) -> bool:
    normalized = str(status or "").casefold()
    return (
        "tombstone" in normalized
        or normalized.startswith("rejected")
        or "private_delete" in normalized
        or "deleted" in normalized
    )

def _is_private_delete_status(status: Any) -> bool:
    return str(status or "").casefold().startswith("private_delete")

def _truncate(value: str, limit: int = 220) -> str:
    compact = _normalize_space(value)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."

def _status_reason(reason: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", reason.casefold()).strip("_")
    return normalized or "unspecified"
