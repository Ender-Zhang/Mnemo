from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


CONTENT_DIMENSIONS = (
    "identity",
    "cognition",
    "values",
    "goals",
    "preferences",
    "relationships",
    "context",
    "history",
    "patterns",
)


@dataclass(frozen=True)
class MemoryQueryPlan:
    original: str
    lexical: tuple[str, ...]
    semantic: tuple[str, ...]
    aliases: tuple[str, ...]
    temporal: str | None
    dimensions: tuple[str, ...]
    should_clarify: bool = False
    clarify_question: str | None = None

    def routes(self) -> list[dict[str, str]]:
        routes: list[dict[str, str]] = []
        for query in self.lexical:
            routes.append({"route": "lexical", "query": query})
        for query in self.semantic:
            routes.append({"route": "semantic", "query": query})
        for query in self.aliases:
            routes.append({"route": "alias", "query": query})
        for query in self.dimensions:
            routes.append({"route": "dimension", "query": query})
        return _dedupe_routes(routes)

    def metadata(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "lexical": list(self.lexical),
            "semantic": list(self.semantic),
            "aliases": list(self.aliases),
            "temporal": self.temporal,
            "dimensions": list(self.dimensions),
            "should_clarify": self.should_clarify,
            "clarify_question": self.clarify_question,
            "routes": self.routes(),
        }


def build_memory_query_plan(query: str, *, l1_snapshot: dict[str, Any] | None = None) -> MemoryQueryPlan:
    original = _normalize_space(query)
    tokens = _query_tokens(original)
    dimensions = tuple(_detect_dimensions(original, tokens))
    temporal = _detect_temporal(original)
    lexical = tuple(_bounded_unique([original, *_proper_like_terms(original), *tokens], limit=8))
    semantic = tuple(_semantic_queries(original, tokens, dimensions, temporal))
    aliases = tuple(_snapshot_aliases(tokens, l1_snapshot))
    return MemoryQueryPlan(
        original=original,
        lexical=lexical,
        semantic=semantic,
        aliases=aliases,
        temporal=temporal,
        dimensions=dimensions,
        should_clarify=False,
    )


def annotate_memory_match(item: dict[str, Any], plan: MemoryQueryPlan, *, score: float) -> dict[str, Any]:
    annotated = dict(item)
    matched_routes = sorted(
        {
            signal.get("route")
            for signal in annotated.get("match_signals", [])
            if isinstance(signal, dict) and signal.get("route")
        }
    )
    annotations = {
        "retrieval_score": round(score, 6),
        "matched_routes": matched_routes,
        "dimensions": list(plan.dimensions),
        "temporal": plan.temporal,
        "stale": _is_stale_status(str(annotated.get("status") or "")),
        "tombstone": _is_tombstone_status(str(annotated.get("status") or "")),
    }
    annotated["retrieval_score"] = round(score, 6)
    annotated["annotations"] = annotations
    return annotated


def fuse_ranked_batches(
    batches: Iterable[tuple[str, str, list[dict[str, Any]]]],
    *,
    plan: MemoryQueryPlan,
    limit: int,
    k: int = 60,
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for route, query, items in batches:
        for rank, item in enumerate(items, start=1):
            item_id = str(item.get("id") or "")
            item_type = str(item.get("type") or "")
            if not item_id or not item_type:
                continue
            key = (item_type, item_id)
            score = 1.0 / (k + rank)
            existing = merged.setdefault(
                key,
                {
                    "item": dict(item),
                    "score": 0.0,
                    "signals": [],
                },
            )
            existing["score"] += score
            existing["signals"].append({"route": route, "query": query, "rank": rank})

    deduped: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()
    for entry in sorted(
        merged.values(),
        key=lambda value: (
            -float(value["score"]),
            -float(value["item"].get("confidence") or 0.0),
            -float(value["item"].get("updated_at") or value["item"].get("created_at") or 0.0),
            str(value["item"].get("id") or ""),
        ),
    ):
        item = dict(entry["item"])
        fingerprint = _result_fingerprint(item)
        if fingerprint and fingerprint in seen_fingerprints:
            continue
        if fingerprint:
            seen_fingerprints.add(fingerprint)
        item["match_signals"] = entry["signals"]
        deduped.append(annotate_memory_match(item, plan, score=float(entry["score"])))
        if len(deduped) >= max(0, int(limit)):
            break
    return deduped


def _dedupe_routes(routes: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for route in routes:
        key = (route["route"], _normalize_space(route["query"]).casefold())
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append({"route": route["route"], "query": _normalize_space(route["query"])})
    return result


def _query_tokens(query: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[\w][\w.-]*", query, flags=re.UNICODE)
        if len(token) >= 2 and token.casefold() not in _STOPWORDS
    ][:12]


def _proper_like_terms(query: str) -> list[str]:
    terms = re.findall(r"\b[A-Z][A-Za-z0-9_.-]{1,}\b|\b[A-Za-z]+[0-9][A-Za-z0-9_.-]*\b", query)
    return terms[:6]


def _semantic_queries(
    original: str,
    tokens: list[str],
    dimensions: tuple[str, ...],
    temporal: str | None,
) -> list[str]:
    queries: list[str] = []
    compact_tokens = [token for token in tokens if token.casefold() not in _DIMENSION_WORDS]
    if compact_tokens and " ".join(compact_tokens).casefold() != original.casefold():
        queries.append(" ".join(compact_tokens[:6]))
    if dimensions and compact_tokens:
        queries.append(" ".join([dimensions[0], *compact_tokens[:4]]))
    if temporal and compact_tokens:
        queries.append(" ".join(compact_tokens[:4]))
    return _bounded_unique(queries, limit=4)


def _detect_dimensions(query: str, tokens: list[str]) -> list[str]:
    text = f" {query.casefold()} "
    token_set = {token.casefold() for token in tokens}
    dimensions: list[str] = []
    for dimension, markers in _DIMENSION_MARKERS.items():
        if dimension in token_set or any(marker in text for marker in markers):
            dimensions.append(dimension)
    return dimensions


def _detect_temporal(query: str) -> str | None:
    text = f" {query.casefold()} "
    for label, markers in _TEMPORAL_MARKERS.items():
        if any(marker in text for marker in markers):
            return label
    year = re.search(r"\b20\d{2}\b", query)
    if year:
        return year.group(0)
    quarter = re.search(r"\b20\d{2}\s*q[1-4]\b|\bq[1-4]\s*20\d{2}\b", query, flags=re.IGNORECASE)
    if quarter:
        return _normalize_space(quarter.group(0).upper())
    return None


def _snapshot_aliases(tokens: list[str], snapshot: dict[str, Any] | None) -> list[str]:
    if not snapshot or not isinstance(snapshot.get("items"), list):
        return []
    query_terms = {token.casefold() for token in tokens}
    aliases: list[str] = []
    for item in snapshot["items"]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or "")
        searchable = f"{title} {summary}".casefold()
        if query_terms and any(term in searchable for term in query_terms):
            aliases.extend(_title_aliases(title))
    return _bounded_unique(aliases, limit=5)


def _title_aliases(title: str) -> list[str]:
    aliases = [_normalize_space(title)]
    if ":" in title:
        aliases.append(_normalize_space(title.split(":", 1)[1]))
    return [alias for alias in aliases if alias]


def _bounded_unique(values: Iterable[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalize_space(value)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _result_fingerprint(item: dict[str, Any]) -> str:
    text = str(item.get("content") or item.get("claim") or item.get("snippet") or "")
    compact = re.sub(r"\W+", "", text.casefold())
    return f"{item.get('type')}:{compact}" if compact else ""


def _is_stale_status(status: str) -> bool:
    normalized = status.casefold()
    return normalized.startswith("stale") or normalized.startswith("archived") or "stale" in normalized


def _is_tombstone_status(status: str) -> bool:
    normalized = status.casefold()
    return (
        "tombstone" in normalized
        or normalized.startswith("rejected")
        or "private_delete" in normalized
        or "deleted" in normalized
    )


def _normalize_space(value: str) -> str:
    return " ".join(str(value or "").strip().split())


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "user",
    "about",
    "what",
    "when",
    "where",
    "我的",
    "关于",
    "什么",
    "一下",
}

_DIMENSION_WORDS = set(CONTENT_DIMENSIONS) | {
    "preference",
    "preferences",
    "goal",
    "goals",
    "history",
    "context",
    "pattern",
    "patterns",
}

_DIMENSION_MARKERS = {
    "identity": (" identity ", " who i am ", "身份", "自我"),
    "cognition": (" cognition ", " thinking ", " learn ", " learning ", "思考", "学习方式"),
    "values": (" values ", " principle ", " principles ", "价值观", "原则"),
    "goals": (" goal ", " goals ", " objective ", "目标", "计划"),
    "preferences": (" preference ", " preferences ", " prefer ", " likes ", "偏好", "喜欢"),
    "relationships": (" relationship ", " relationships ", " team ", "people", "关系", "同事"),
    "context": (" context ", " project ", " current ", "上下文", "项目", "当前"),
    "history": (" history ", " past ", " previous ", "以前", "过去", "历史"),
    "patterns": (" pattern ", " patterns ", " habit ", "常用", "模式", "习惯"),
}

_TEMPORAL_MARKERS = {
    "recent": (" recent ", " recently ", " latest ", "当前", "最近", "刚刚"),
    "today": (" today ", "今天"),
    "yesterday": (" yesterday ", "昨天"),
    "last_week": (" last week ", "上周"),
    "last_month": (" last month ", "上个月"),
    "this_year": (" this year ", "今年"),
}
