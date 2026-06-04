from __future__ import annotations

import re
from typing import Any, Iterable

from .query import CONTENT_DIMENSIONS, normalize_memory_dimension
from .utils import _bounded_confidence, _normalize_space, _truncate


ASSOCIATION_SCAN_LIMIT = 1000


def compact_wiki_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    source = metadata if isinstance(metadata, dict) else {}
    compact: dict[str, Any] = {}
    for key in ("expires", "expires_at", "decay_days", "last_verified_at", "verified_at"):
        value = source.get(key)
        if value is not None and str(value).strip():
            compact[key] = value

    aliases = compact_aliases(source)
    if aliases:
        compact["aliases"] = aliases

    links = compact_link_refs(source.get("links") or source.get("wiki_links"))
    if links:
        compact["links"] = links

    associations = compact_associations(source.get("associations"))
    if associations:
        compact["associations"] = associations

    exposure = _compact_mapping(source.get("exposure"), allowed_keys=("min_level", "agent_types"))
    if exposure:
        compact["exposure"] = exposure

    watches = _compact_string_list(source.get("watches"), limit=12, item_limit=96)
    if watches:
        compact["watches"] = watches
    return compact


def compact_aliases(metadata: dict[str, Any] | None) -> list[str]:
    source = metadata if isinstance(metadata, dict) else {}
    return _compact_string_list(source.get("aliases") or source.get("alias"), limit=16, item_limit=96)


def compact_link_refs(value: Any) -> list[str]:
    refs: list[str] = []
    for item in _iter_list(value):
        ref = _association_ref(item)
        if ref:
            refs.append(ref)
    return _dedupe_strings(refs, limit=24)


def compact_associations(value: Any) -> list[dict[str, Any]]:
    associations: list[dict[str, Any]] = []
    for item in _iter_list(value):
        if isinstance(item, dict):
            target = _association_ref(item)
            if not target:
                continue
            association: dict[str, Any] = {"target": target}
            if item.get("strength") is not None:
                association["strength"] = round(_bounded_confidence(item.get("strength"), 0.6), 3)
            reason = _normalize_space(str(item.get("reason") or item.get("why") or ""))
            if reason:
                association["reason"] = _truncate(reason, limit=180)
            evidence = _normalize_space(str(item.get("evidence") or item.get("evidence_ref") or ""))
            if evidence:
                association["evidence"] = _truncate(evidence, limit=120)
            associations.append(association)
            continue
        target = _normalize_space(str(item or ""))
        if target:
            associations.append({"target": _truncate(target, limit=160)})
    return _dedupe_associations(associations, limit=24)


def metadata_alias_pages(store: Any, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    query_text = _normalize_reference(query)
    query_terms = set(_reference_terms(query))
    if not query_text and not query_terms:
        return []

    pages = _active_pages(store, limit=max(ASSOCIATION_SCAN_LIMIT, limit))
    matched: list[dict[str, Any]] = []
    for page in pages:
        aliases = compact_aliases(_page_metadata(page))
        if not aliases:
            continue
        if any(_alias_matches_query(alias, query_text=query_text, query_terms=query_terms) for alias in aliases):
            matched.append(page)
        if len(matched) >= max(0, int(limit)):
            break
    return matched


def metadata_association_links_for_page(
    store: Any,
    page_id: str,
    *,
    limit: int = ASSOCIATION_SCAN_LIMIT,
) -> list[tuple[dict[str, Any], str]]:
    page = _get_page(store, page_id)
    if not page or page.get("status") != "active":
        return []
    pages = _active_pages(store, limit=max(1, int(limit)))
    index = _PageReferenceIndex(pages)
    links = page_metadata_association_edges(page, index=index)

    for source in pages:
        source_id = str(source.get("id") or "")
        if not source_id or source_id == page_id:
            continue
        for link, target_id in page_metadata_association_edges(source, index=index):
            if target_id != page_id:
                continue
            links.append((_reverse_link(link, seed_page_id=page_id), source_id))

    return _dedupe_links(links)


def page_metadata_association_edges(
    page: dict[str, Any],
    *,
    active_pages: list[dict[str, Any]] | None = None,
    index: "_PageReferenceIndex | None" = None,
) -> list[tuple[dict[str, Any], str]]:
    page_id = str(page.get("id") or "")
    if not page_id:
        return []
    reference_index = index or _PageReferenceIndex(active_pages or [page])
    metadata = _page_metadata(page)
    created_at = float(page.get("updated_at") or page.get("created_at") or 0.0)
    edges: list[tuple[dict[str, Any], str]] = []

    for order, item in enumerate(_iter_list(metadata.get("links") or metadata.get("wiki_links")), start=1):
        ref = _association_ref(item)
        target_id = reference_index.resolve(ref)
        if not target_id or target_id == page_id:
            continue
        edges.append(
            (
                _metadata_link(
                    page_id,
                    target_id,
                    relation=_relation(item, default="wiki_link"),
                    weight=_strength(item, default=0.55),
                    created_at=created_at,
                    order=order,
                    reason=_reason(item),
                    evidence=_evidence(item),
                    target_ref=ref,
                ),
                target_id,
            )
        )

    for order, item in enumerate(_iter_list(metadata.get("associations")), start=1):
        ref = _association_ref(item)
        target_id = reference_index.resolve(ref)
        if not target_id or target_id == page_id:
            continue
        edges.append(
            (
                _metadata_link(
                    page_id,
                    target_id,
                    relation=_relation(item, default="association"),
                    weight=_strength(item, default=0.65),
                    created_at=created_at,
                    order=order,
                    reason=_reason(item),
                    evidence=_evidence(item),
                    target_ref=ref,
                ),
                target_id,
            )
        )
    return _dedupe_links(edges)


def has_metadata_associations(store: Any, page_id: str) -> bool:
    return bool(metadata_association_links_for_page(store, page_id, limit=ASSOCIATION_SCAN_LIMIT))


class _PageReferenceIndex:
    def __init__(self, pages: Iterable[dict[str, Any]]):
        self._ids: set[str] = set()
        self._keys: dict[str, str] = {}
        for page in pages:
            page_id = str(page.get("id") or "")
            if not page_id or page.get("status") != "active":
                continue
            self._ids.add(page_id)
            for key in _page_reference_keys(page):
                self._keys.setdefault(key, page_id)

    def resolve(self, reference: Any) -> str | None:
        text = _normalize_space(str(reference or ""))
        if not text:
            return None
        if text in self._ids:
            return text
        for key in _reference_keys(text):
            page_id = self._keys.get(key)
            if page_id:
                return page_id
        return None


def _active_pages(store: Any, *, limit: int) -> list[dict[str, Any]]:
    list_pages = getattr(store, "list_memory_pages", None)
    if not list_pages:
        return []
    return list_pages(status="active", limit=max(0, int(limit)))


def _get_page(store: Any, page_id: str) -> dict[str, Any] | None:
    get_page = getattr(store, "get_memory_page", None)
    if get_page:
        return get_page(page_id)
    return None


def _page_metadata(page: dict[str, Any]) -> dict[str, Any]:
    metadata = page.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _metadata_link(
    source_id: str,
    target_id: str,
    *,
    relation: str,
    weight: float,
    created_at: float,
    order: int,
    reason: str | None,
    evidence: str | None,
    target_ref: str,
) -> dict[str, Any]:
    link = {
        "id": f"meta:{source_id}:{relation}:{target_id}:{order}",
        "source_id": source_id,
        "target_id": target_id,
        "relation": relation,
        "weight": round(weight, 6),
        "created_at": created_at,
        "source": "metadata",
        "target_ref": target_ref,
    }
    if reason:
        link["reason"] = reason
    if evidence:
        link["evidence"] = evidence
    return link


def _reverse_link(link: dict[str, Any], *, seed_page_id: str) -> dict[str, Any]:
    relation = str(link.get("relation") or "association")
    reverse_relation = "wiki_backlink" if relation == "wiki_link" else f"{relation}_backlink"
    reversed_link = dict(link)
    reversed_link["id"] = f"{link.get('id')}:backlink:{seed_page_id}"
    reversed_link["relation"] = reverse_relation
    reversed_link["target_id"] = seed_page_id
    return reversed_link


def _dedupe_links(links: Iterable[tuple[dict[str, Any], str]]) -> list[tuple[dict[str, Any], str]]:
    best: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
    for link, target_id in links:
        key = (str(target_id), str(link.get("relation") or ""))
        existing = best.get(key)
        if existing is None or _link_sort_key((link, target_id)) < _link_sort_key(existing):
            best[key] = (link, target_id)
    return sorted(best.values(), key=_link_sort_key)


def _link_sort_key(item: tuple[dict[str, Any], str]) -> tuple[float, float, str]:
    link, target_id = item
    return (
        -float(link.get("weight", 0.0)),
        -float(link.get("created_at", 0.0)),
        str(link.get("id") or target_id),
    )


def _page_reference_keys(page: dict[str, Any]) -> set[str]:
    page_id = str(page.get("id") or "")
    title = _normalize_space(str(page.get("title") or ""))
    title_body = title.split(":", 1)[1].strip() if ":" in title else title
    dimension = _page_dimension(page)
    metadata = _page_metadata(page)
    keys = {
        *_reference_keys(page_id),
        *_reference_keys(f"{dimension}/{page_id}"),
        *_reference_keys(f"wiki/{dimension}/{page_id}.md"),
        *_reference_keys(title),
        *_reference_keys(title_body),
        *_reference_keys(f"{dimension}/{_slug(title_body)}"),
        *_reference_keys(f"wiki/{dimension}/{_slug(title_body)}.md"),
    }
    for value in (
        metadata.get("path"),
        metadata.get("wiki_path"),
        metadata.get("slug"),
    ):
        keys.update(_reference_keys(value))
    for alias in compact_aliases(metadata):
        keys.update(_reference_keys(alias))
        keys.update(_reference_keys(f"{dimension}/{_slug(alias)}"))
    return {key for key in keys if key}


def _reference_keys(value: Any) -> set[str]:
    text = _normalize_reference(value)
    if not text:
        return set()
    without_anchor = text.split("#", 1)[0]
    without_wiki = without_anchor.removeprefix("wiki/")
    without_md = without_wiki[:-3] if without_wiki.endswith(".md") else without_wiki
    values = {text, without_anchor, without_wiki, without_md}
    if "/" not in without_md:
        values.add(_slug(without_md))
    return {_normalize_reference(item) for item in values if item}


def _normalize_reference(value: Any) -> str:
    text = _normalize_space(str(value or ""))
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.strip().strip("\"'")
    text = text.replace("\\", "/")
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"/+", "/", text)
    return text.casefold().strip("/")


def _slug(value: str) -> str:
    parts = re.findall(r"[\w]+", str(value or "").casefold(), flags=re.UNICODE)
    return "-".join(parts)


def _page_dimension(page: dict[str, Any]) -> str:
    metadata = _page_metadata(page)
    title = str(page.get("title") or "")
    title_head = title.split(":", 1)[0] if ":" in title else ""
    for value in (metadata.get("dimension"), title_head, page.get("scope")):
        if not str(value or "").strip():
            continue
        dimension = normalize_memory_dimension(str(value), fallback="", allow_policy=False)
        if dimension in CONTENT_DIMENSIONS:
            return dimension
    return "context"


def _association_ref(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("target_id", "page_id", "id", "path", "target", "wiki_path", "href", "ref"):
            value = item.get(key)
            if value is not None and str(value).strip():
                return _truncate(_normalize_space(str(value)), limit=160)
        return ""
    return _truncate(_normalize_space(str(item or "")), limit=160)


def _relation(item: Any, *, default: str) -> str:
    if isinstance(item, dict):
        relation = _normalize_space(str(item.get("relation") or item.get("type") or ""))
        if relation:
            return _slug(relation).replace("-", "_") or default
    return default


def _strength(item: Any, *, default: float) -> float:
    if isinstance(item, dict):
        return _bounded_confidence(item.get("strength") if item.get("strength") is not None else item.get("weight"), default)
    return default


def _reason(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    reason = _normalize_space(str(item.get("reason") or item.get("why") or item.get("why_relevant") or ""))
    return _truncate(reason, limit=180) if reason else None


def _evidence(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    evidence = _normalize_space(str(item.get("evidence") or item.get("evidence_ref") or item.get("source") or ""))
    return _truncate(evidence, limit=120) if evidence else None


def _iter_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _compact_string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    items = [_truncate(_normalize_space(str(item)), limit=item_limit) for item in _iter_list(value)]
    return _dedupe_strings([item for item in items if item], limit=limit)


def _compact_mapping(value: Any, *, allowed_keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in allowed_keys:
        if key not in value:
            continue
        item = value.get(key)
        if isinstance(item, (list, tuple)):
            values = _compact_string_list(item, limit=12, item_limit=80)
            if values:
                compact[key] = values
            continue
        text = _normalize_space(str(item or ""))
        if text:
            compact[key] = _truncate(text, limit=120)
    return compact


def _dedupe_strings(values: Iterable[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = _normalize_reference(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= max(0, int(limit)):
            break
    return result


def _dedupe_associations(values: Iterable[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = _normalize_reference(value.get("target"))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= max(0, int(limit)):
            break
    return result


def _alias_matches_query(alias: str, *, query_text: str, query_terms: set[str]) -> bool:
    alias_text = _normalize_reference(alias)
    if query_text and (query_text in alias_text or alias_text in query_text):
        return True
    alias_terms = set(_reference_terms(alias))
    return bool(alias_terms and query_terms and alias_terms & query_terms)


def _reference_terms(value: Any) -> list[str]:
    return [
        token
        for token in re.findall(r"[\w]+", _normalize_reference(value), flags=re.UNICODE)
        if len(token) >= 2
    ]
