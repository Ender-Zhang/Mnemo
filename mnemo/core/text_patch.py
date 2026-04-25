from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class TextPatchError(ValueError):
    pass


def normalize_text_replacements(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise TextPatchError("missing replacement array argument: replacements")
    replacements: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise TextPatchError(f"replacement {index} must be an object")
        old = item.get("old")
        new = item.get("new")
        if not isinstance(old, str) or not old:
            raise TextPatchError(f"replacement {index} old text must be a non-empty string")
        if not isinstance(new, str):
            raise TextPatchError(f"replacement {index} new text must be a string")
        replacements.append({"old": old, "new": new})
    return replacements


def optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TextPatchError("expected boolean argument")
    return value


def apply_exact_replacements(
    content: str,
    replacements: list[dict[str, str]],
    *,
    replace_all: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    updated = content
    applied: list[dict[str, Any]] = []

    for index, replacement in enumerate(replacements):
        old = replacement["old"]
        new = replacement["new"]
        count = updated.count(old)
        if count == 0:
            raise TextPatchError(f"replacement {index} text not found")
        if count > 1 and not replace_all:
            raise TextPatchError(f"replacement {index} is ambiguous; pass replace_all=true")
        applied_count = count if replace_all else 1
        updated = updated.replace(old, new, applied_count)
        applied.append(
            {
                "index": index,
                "count": applied_count,
                "old_bytes": len(old.encode("utf-8")),
                "new_bytes": len(new.encode("utf-8")),
            }
        )

    return updated, applied
