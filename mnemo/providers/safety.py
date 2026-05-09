from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

PROVIDER_SAFETY_REJECTION_MESSAGE = "provider rejected request as high risk"

_REJECTION_TEXTS = (
    "the request was rejected because it was considered high risk",
)
_CONTENT_FILTER_REASONS = {"content_filter", "content-filter"}


def provider_rejection_reason_from_text(text: str) -> str | None:
    normalized = _normalize_provider_text(text).rstrip(".。!")
    if normalized in _REJECTION_TEXTS:
        return PROVIDER_SAFETY_REJECTION_MESSAGE
    return None


def provider_rejection_reason_from_metadata(metadata: Iterable[Mapping[str, Any]]) -> str | None:
    for item in metadata:
        finish_reason = _normalize_reason(item.get("finish_reason"))
        stop_reason = _normalize_reason(item.get("stop_reason"))
        if finish_reason in _CONTENT_FILTER_REASONS or stop_reason in _CONTENT_FILTER_REASONS:
            return PROVIDER_SAFETY_REJECTION_MESSAGE
    return None


def is_provider_rejection_prefix(text: str) -> bool:
    normalized = _normalize_provider_text(text)
    if not normalized:
        return False
    return any(rejection.startswith(normalized) for rejection in _REJECTION_TEXTS)


def _normalize_provider_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _normalize_reason(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().casefold().replace(" ", "_")
