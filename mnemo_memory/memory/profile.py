from __future__ import annotations

from typing import Any

from .query import CONTENT_DIMENSIONS, normalize_memory_dimension
from .utils import _normalize_space, _truncate

L0_PRIORITY_DIMENSIONS = ("identity", "preferences", "goals", "context", "patterns")
L0_SECONDARY_DIMENSIONS = ("cognition", "values", "relationships", "history")
L0_MAX_PAGES_PER_DIMENSION = 3
L0_MAX_TOTAL_ITEMS = 12
L0_CONTENT_TRUNCATE = 120


def compile_l0_profile(
    pages: list[dict[str, Any]],
    *,
    max_items: int = L0_MAX_TOTAL_ITEMS,
) -> dict[str, Any]:
    """Compile a compact L0 profile card from active memory pages.

    Returns a ~200-400 token profile card suitable for injection every turn.
    """
    active = [p for p in pages if p.get("status") == "active"]
    if not active:
        return {"kind": "l0_profile", "summary": "", "dimensions": {}, "page_count": 0}

    by_dim = _group_by_dimension(active)

    dimensions: dict[str, list[str]] = {}
    total = 0
    bounded = max(1, int(max_items))

    for dim in (*L0_PRIORITY_DIMENSIONS, *L0_SECONDARY_DIMENSIONS):
        if total >= bounded:
            break
        dim_pages = by_dim.get(dim, [])
        if not dim_pages:
            continue
        statements: list[str] = []
        for page in dim_pages[:L0_MAX_PAGES_PER_DIMENSION]:
            if total >= bounded:
                break
            statement = _page_statement(page)
            if statement:
                statements.append(statement)
                total += 1
        if statements:
            dimensions[dim] = statements

    summary = _render_summary(dimensions)
    return {
        "kind": "l0_profile",
        "summary": summary,
        "dimensions": dimensions,
        "page_count": len(active),
    }


def _group_by_dimension(pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for page in sorted(pages, key=_confidence_recency_key):
        dim = _page_dimension(page)
        groups.setdefault(dim, []).append(page)
    return groups


def _page_dimension(page: dict[str, Any]) -> str:
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    title = str(page.get("title") or "")
    title_head = title.split(":", 1)[0] if ":" in title else ""
    for value in (metadata.get("dimension"), title_head, page.get("scope")):
        if not str(value or "").strip():
            continue
        dim = normalize_memory_dimension(str(value), fallback="", allow_policy=False)
        if dim in CONTENT_DIMENSIONS:
            return dim
    return "context"


def _page_statement(page: dict[str, Any]) -> str:
    title = _normalize_space(str(page.get("title") or ""))
    content = _normalize_space(str(page.get("content") or ""))
    if title and content:
        title_body = title.split(":", 1)[1].strip() if ":" in title else title
        return _truncate(f"{title_body}: {content}", limit=L0_CONTENT_TRUNCATE)
    return _truncate(title or content, limit=L0_CONTENT_TRUNCATE)


def _render_summary(dimensions: dict[str, list[str]]) -> str:
    if not dimensions:
        return ""
    parts: list[str] = []
    for dim, statements in dimensions.items():
        label = _dimension_label(dim)
        joined = "; ".join(statements)
        parts.append(f"[{label}] {joined}")
    return "\n".join(parts)


_DIMENSION_LABELS = {
    "identity": "身份",
    "cognition": "认知",
    "values": "价值观",
    "goals": "目标",
    "preferences": "偏好",
    "relationships": "关系",
    "context": "情境",
    "history": "历史",
    "patterns": "模式",
    "boundaries": "边界",
}


def _dimension_label(dim: str) -> str:
    return _DIMENSION_LABELS.get(dim, dim)


def _confidence_recency_key(page: dict[str, Any]) -> tuple[float, float, str]:
    return (
        -float(page.get("confidence") or 0.0),
        -float(page.get("updated_at") or page.get("created_at") or 0.0),
        str(page.get("id") or ""),
    )
