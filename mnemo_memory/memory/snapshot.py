from __future__ import annotations

import time
from typing import Any, Iterable

from .associations import compact_aliases, page_metadata_association_edges
from .cards import _snapshot_item
from .query import CONTENT_DIMENSIONS, normalize_memory_dimension
from .utils import _bounded_confidence, _normalize_space, _truncate


L1_POINTER_LIMIT = 32
L1_ASSOCIATION_HUB_LIMIT = 8
L1_POINTER_ASSOCIATION_LIMIT = 3
L1_POINTER_TRIGGER_LIMIT = 3


def compile_l1_snapshot_payload(
    store: Any,
    pages: list[dict[str, Any]],
    *,
    generated_at: float | None = None,
) -> dict[str, Any]:
    active_pages = [page for page in pages if page.get("status") == "active"]
    items = [_snapshot_item(page) for page in active_pages]
    graph = _compile_l1_association_graph(store, active_pages)
    pointers = _compile_l1_pointers(active_pages, graph)
    association_hubs = _compile_l1_association_hubs(active_pages, graph)
    snapshot: dict[str, Any] = {
        "kind": "l1_memory_snapshot",
        "generated_at": time.time() if generated_at is None else float(generated_at),
        "page_count": len(items),
        "items": items,
    }
    if pointers:
        snapshot["pointers"] = pointers
    if association_hubs:
        snapshot["association_hubs"] = association_hubs
    return snapshot


def _compile_l1_pointers(
    pages: list[dict[str, Any]],
    graph: dict[str, Any],
    *,
    limit: int = L1_POINTER_LIMIT,
) -> list[dict[str, Any]]:
    pointers: list[dict[str, Any]] = []
    for page in sorted(pages, key=_page_priority_key):
        page_id = str(page.get("id") or "")
        if not page_id:
            continue
        triggers = _page_triggers(page)
        if not triggers:
            continue
        pointer: dict[str, Any] = {
            "trigger": triggers[0],
            "page_id": page_id,
            "target": _page_target(page),
            "title": _truncate(str(page.get("title") or ""), limit=96),
            "confidence": page.get("confidence"),
        }
        if len(triggers) > 1:
            pointer["aliases"] = triggers[1:L1_POINTER_TRIGGER_LIMIT]
        associations = _pointer_associations(page_id, graph)
        if associations:
            pointer["associations"] = associations
        pointers.append(pointer)
        if len(pointers) >= max(0, int(limit)):
            break
    return pointers


def _compile_l1_association_hubs(
    pages: list[dict[str, Any]],
    graph: dict[str, Any],
    *,
    limit: int = L1_ASSOCIATION_HUB_LIMIT,
) -> list[dict[str, Any]]:
    pages_by_id = {str(page.get("id") or ""): page for page in pages}
    hubs: list[dict[str, Any]] = []
    for page_id, edges in graph["incoming"].items():
        page = pages_by_id.get(page_id)
        if not page:
            continue
        source_ids = sorted({str(edge.get("source_id") or "") for edge in edges if edge.get("source_id")})
        if len(source_ids) < 2:
            continue
        triggers = [_page_primary_trigger(pages_by_id[source_id]) for source_id in source_ids if source_id in pages_by_id]
        reasons = [
            _truncate(str(edge.get("reason") or ""), limit=120)
            for edge in edges
            if str(edge.get("reason") or "").strip()
        ]
        hub: dict[str, Any] = {
            "page_id": page_id,
            "target": _page_target(page),
            "title": _truncate(str(page.get("title") or ""), limit=96),
            "incoming_count": len(edges),
            "source_count": len(source_ids),
            "triggers": _dedupe_strings(triggers, limit=4),
        }
        if reasons:
            hub["why"] = reasons[0]
        hubs.append(hub)
    return sorted(
        hubs,
        key=lambda item: (
            -int(item.get("source_count") or 0),
            -int(item.get("incoming_count") or 0),
            str(item.get("target") or ""),
        ),
    )[: max(0, int(limit))]


def _compile_l1_association_graph(store: Any, pages: list[dict[str, Any]]) -> dict[str, Any]:
    active_ids = {str(page.get("id") or "") for page in pages if page.get("id")}
    pages_by_id = {str(page.get("id") or ""): page for page in pages if page.get("id")}
    edges_by_source: dict[str, list[dict[str, Any]]] = {page_id: [] for page_id in active_ids}
    incoming: dict[str, list[dict[str, Any]]] = {page_id: [] for page_id in active_ids}
    for page in pages:
        source_id = str(page.get("id") or "")
        if not source_id:
            continue
        for edge in _page_l1_edges(store, page, active_ids=active_ids, active_pages=pages):
            target_id = str(edge.get("target_id") or "")
            if target_id not in active_ids or target_id == source_id:
                continue
            edges_by_source.setdefault(source_id, []).append(edge)
            incoming.setdefault(target_id, []).append(edge)
    return {
        "pages_by_id": pages_by_id,
        "outgoing": {source_id: _dedupe_edges(edges) for source_id, edges in edges_by_source.items()},
        "incoming": {target_id: _dedupe_edges(edges) for target_id, edges in incoming.items()},
    }


def _page_l1_edges(
    store: Any,
    page: dict[str, Any],
    *,
    active_ids: set[str],
    active_pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    page_id = str(page.get("id") or "")
    edges: list[dict[str, Any]] = []
    list_links = getattr(store, "list_memory_links", None)
    if list_links:
        for link in list_links(page_id):
            relation = str(link.get("relation") or "")
            target_id = str(link.get("target_id") or "")
            if target_id not in active_ids or relation in {"promoted_to", "conflicts_with", "superseded_by"}:
                continue
            edges.append(_compact_l1_edge(link, source_id=page_id, target_id=target_id))
    for link, target_id in page_metadata_association_edges(page, active_pages=active_pages):
        if target_id in active_ids:
            edges.append(_compact_l1_edge(link, source_id=page_id, target_id=target_id))
    return _dedupe_edges(edges)


def _compact_l1_edge(link: dict[str, Any], *, source_id: str, target_id: str) -> dict[str, Any]:
    edge = {
        "source_id": source_id,
        "target_id": target_id,
        "relation": str(link.get("relation") or "related"),
        "weight": round(_bounded_confidence(link.get("weight"), 0.5), 6),
        "created_at": float(link.get("created_at") or 0.0),
    }
    reason = _normalize_space(str(link.get("reason") or ""))
    if reason:
        edge["reason"] = _truncate(reason, limit=120)
    return edge


def _pointer_associations(page_id: str, graph: dict[str, Any]) -> list[str]:
    pages_by_id = graph.get("pages_by_id") or {}
    associations: list[str] = []
    for edge in graph["outgoing"].get(page_id, []):
        target_id = str(edge.get("target_id") or "")
        page = pages_by_id.get(target_id)
        associations.append(_page_short_label(page) if page else target_id)
    return _dedupe_strings(associations, limit=L1_POINTER_ASSOCIATION_LIMIT)


def _page_triggers(page: dict[str, Any]) -> list[str]:
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    triggers = [
        *compact_aliases(metadata),
        _page_title_body(page),
        _page_dimension(page),
    ]
    return _dedupe_strings([_truncate(trigger, limit=80) for trigger in triggers], limit=L1_POINTER_TRIGGER_LIMIT)


def _page_primary_trigger(page: dict[str, Any]) -> str:
    triggers = _page_triggers(page)
    return triggers[0] if triggers else _page_short_label(page)


def _page_short_label(page: dict[str, Any] | None) -> str:
    if not page:
        return ""
    title_body = _page_title_body(page)
    return title_body or str(page.get("id") or "")


def _page_target(page: dict[str, Any]) -> str:
    return f"{_page_dimension(page)}#{_slug(_page_title_body(page) or str(page.get('id') or 'memory'))}"


def _page_title_body(page: dict[str, Any]) -> str:
    title = _normalize_space(str(page.get("title") or ""))
    return title.split(":", 1)[1].strip() if ":" in title else title


def _page_dimension(page: dict[str, Any]) -> str:
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    title = str(page.get("title") or "")
    title_head = title.split(":", 1)[0] if ":" in title else ""
    for value in (metadata.get("dimension"), title_head, page.get("scope")):
        if not str(value or "").strip():
            continue
        dimension = normalize_memory_dimension(str(value), fallback="", allow_policy=False)
        if dimension in CONTENT_DIMENSIONS:
            return dimension
    return "context"


def _page_priority_key(page: dict[str, Any]) -> tuple[float, float, str]:
    return (
        -float(page.get("confidence") or 0.0),
        -float(page.get("updated_at") or page.get("created_at") or 0.0),
        str(page.get("id") or ""),
    )


def _dedupe_edges(edges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in edges:
        key = (
            str(edge.get("source_id") or ""),
            str(edge.get("target_id") or ""),
            str(edge.get("relation") or ""),
        )
        existing = best.get(key)
        if existing is None or _edge_sort_key(edge) < _edge_sort_key(existing):
            best[key] = edge
    return sorted(best.values(), key=_edge_sort_key)


def _edge_sort_key(edge: dict[str, Any]) -> tuple[float, float, str]:
    return (
        -float(edge.get("weight") or 0.0),
        -float(edge.get("created_at") or 0.0),
        str(edge.get("target_id") or ""),
    )


def _dedupe_strings(values: Iterable[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _normalize_space(str(value or ""))
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= max(0, int(limit)):
            break
    return result


def _slug(value: str) -> str:
    return "-".join(_normalize_space(value).casefold().replace("_", "-").split())
