from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .associations import compact_wiki_metadata
from .query import CONTENT_DIMENSIONS, normalize_memory_dimension
from .utils import _normalize_space


def materialize_memory_page(state_dir: str | Path, page: dict[str, Any]) -> dict[str, Any]:
    page_id = str(page.get("id") or "").strip()
    if not page_id:
        raise ValueError("memory page id is required for wiki materialization")
    path = memory_page_wiki_path(state_dir, page)
    path.parent.mkdir(parents=True, exist_ok=True)
    remove_memory_page_wiki_files(state_dir, page_id, keep=path)
    markdown = render_memory_page_markdown(page)
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp_path.write_text(markdown, encoding="utf-8")
    os.replace(tmp_path, path)
    return {
        "path": _relative_wiki_path(state_dir, path),
        "content_hash": memory_page_content_hash(page),
    }


def materialize_memory_pages(state_dir: str | Path, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [materialize_memory_page(state_dir, page) for page in pages]


def remove_memory_page_wiki_files(
    state_dir: str | Path,
    page_id: str,
    *,
    keep: Path | None = None,
) -> list[str]:
    root = Path(state_dir).expanduser().resolve() / "wiki"
    safe_id = _safe_page_id(page_id)
    if not root.exists() or not safe_id:
        return []
    kept = keep.expanduser().resolve() if keep else None
    removed: list[str] = []
    for path in root.glob(f"**/{safe_id}.md"):
        resolved = path.resolve()
        if kept and resolved == kept:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(_relative_wiki_path(state_dir, resolved))
    return removed


def memory_page_wiki_path(state_dir: str | Path, page: dict[str, Any]) -> Path:
    page_id = _safe_page_id(str(page.get("id") or ""))
    if not page_id:
        raise ValueError("memory page id is required for wiki path")
    status = str(page.get("status") or "active").casefold()
    if status.startswith("private_delete"):
        folder = "_redacted"
    elif status.startswith(("archived", "stale", "tombstoned")):
        folder = "_archive"
    else:
        folder = memory_page_dimension(page)
    return Path(state_dir).expanduser().resolve() / "wiki" / folder / f"{page_id}.md"


def render_memory_page_markdown(page: dict[str, Any]) -> str:
    title = _display_title(str(page.get("title") or "Memory"))
    content = str(page.get("content") or "").strip() or "_No memory body._"
    frontmatter = {
        "id": page.get("id"),
        "dimension": memory_page_dimension(page),
        "status": page.get("status") or "active",
        "confidence": page.get("confidence"),
        "scope": page.get("scope") or "global",
        "source_candidate_id": page.get("source_candidate_id"),
        "created_at": _iso_timestamp(page.get("created_at")),
        "updated_at": _iso_timestamp(page.get("updated_at")),
        "content_hash": memory_page_content_hash(page),
    }
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    frontmatter.update(compact_wiki_metadata(metadata))
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.extend(_frontmatter_lines(key, value))
    lines.extend(["---", "", f"# {title}", "", content, ""])
    return "\n".join(lines)


def memory_page_dimension(page: dict[str, Any]) -> str:
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    for value in (metadata.get("dimension"), _title_dimension(page), page.get("scope")):
        if not str(value or "").strip():
            continue
        dimension = normalize_memory_dimension(str(value or ""), fallback="", allow_policy=False)
        if dimension in CONTENT_DIMENSIONS:
            return dimension
    return "context"


def memory_page_content_hash(page: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "id": page.get("id"),
            "title": page.get("title"),
            "content": page.get("content"),
            "status": page.get("status"),
            "confidence": page.get("confidence"),
            "scope": page.get("scope"),
            "source_candidate_id": page.get("source_candidate_id"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _title_dimension(page: dict[str, Any]) -> str:
    title = str(page.get("title") or "")
    return title.split(":", 1)[0] if ":" in title else ""


def _display_title(value: str) -> str:
    text = _normalize_space(str(value or ""))
    if ":" not in text:
        return text or "Memory"
    head, body = text.split(":", 1)
    dimension = normalize_memory_dimension(head, fallback="", allow_policy=False)
    if dimension in CONTENT_DIMENSIONS:
        return body.strip() or head.strip()
    return text or "Memory"


def _frontmatter_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple)):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(round(float(value), 6)).rstrip("0").rstrip(".")
    text = str(value).strip()
    if not text:
        return None
    return json.dumps(text, ensure_ascii=False)


def _frontmatter_lines(key: str, value: Any, *, indent: int = 0) -> list[str]:
    prefix = " " * indent
    encoded = _frontmatter_value(value)
    if encoded is not None:
        return [f"{prefix}{key}: {encoded}"]
    if isinstance(value, list):
        if not value:
            return []
        lines = [f"{prefix}{key}:"]
        for item in value:
            lines.extend(_frontmatter_list_item_lines(item, indent=indent + 2))
        return lines
    if isinstance(value, dict):
        if not value:
            return []
        lines = [f"{prefix}{key}:"]
        for child_key, child_value in value.items():
            lines.extend(_frontmatter_lines(str(child_key), child_value, indent=indent + 2))
        return lines
    return []


def _frontmatter_list_item_lines(value: Any, *, indent: int) -> list[str]:
    prefix = " " * indent
    encoded = _frontmatter_value(value)
    if encoded is not None:
        return [f"{prefix}- {encoded}"]
    if isinstance(value, dict) and value:
        items = list(value.items())
        first_key, first_value = items[0]
        first_encoded = _frontmatter_value(first_value)
        if first_encoded is not None:
            lines = [f"{prefix}- {first_key}: {first_encoded}"]
        else:
            lines = [f"{prefix}- {first_key}:"]
            lines.extend(_frontmatter_nested_value_lines(first_value, indent=indent + 4))
        for child_key, child_value in items[1:]:
            lines.extend(_frontmatter_lines(str(child_key), child_value, indent=indent + 2))
        return lines
    return []


def _frontmatter_nested_value_lines(value: Any, *, indent: int) -> list[str]:
    prefix = " " * indent
    encoded = _frontmatter_value(value)
    if encoded is not None:
        return [f"{prefix}{encoded}"]
    if isinstance(value, list):
        return [
            line
            for item in value
            for line in _frontmatter_list_item_lines(item, indent=indent)
        ]
    if isinstance(value, dict):
        return [
            line
            for child_key, child_value in value.items()
            for line in _frontmatter_lines(str(child_key), child_value, indent=indent)
        ]
    return []


def _iso_timestamp(value: Any) -> str | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat()


def _safe_page_id(value: str) -> str:
    return "".join(char for char in str(value or "") if char.isalnum() or char in {"_", "-"})


def _relative_wiki_path(state_dir: str | Path, path: Path) -> str:
    root = Path(state_dir).expanduser().resolve()
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()
