from __future__ import annotations

import hashlib
import math
import struct
from typing import Any, Protocol

from .cards import _page_result
from .utils import _normalize_space


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def encode_embedding(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def decode_embedding(data: bytes) -> list[float]:
    count = len(data) // 4
    return list(struct.unpack(f"<{count}f", data[:count * 4]))


def content_hash(text: str) -> str:
    return hashlib.sha256(_normalize_space(text).encode("utf-8")).hexdigest()[:16]


def ensure_page_embeddings(
    store: Any,
    provider: EmbeddingProvider,
    pages: list[dict[str, Any]],
    model: str,
) -> int:
    to_embed: list[tuple[dict[str, Any], str]] = []
    for page in pages:
        page_id = str(page.get("id") or "")
        if not page_id:
            continue
        text = _page_embedding_text(page)
        text_hash = content_hash(text)
        existing = store.get_embedding(page_id)
        if existing and existing.get("content_hash") == text_hash:
            continue
        to_embed.append((page, text_hash))

    if not to_embed:
        return 0

    texts = [_page_embedding_text(page) for page, _ in to_embed]
    embeddings = provider.embed_texts(texts)

    stored = 0
    for (page, text_hash), embedding in zip(to_embed, embeddings):
        if not embedding:
            continue
        store.store_embedding(
            target_id=str(page["id"]),
            target_type="page",
            content_hash=text_hash,
            embedding_bytes=encode_embedding(embedding),
            model=model,
            dimensions=len(embedding),
        )
        stored += 1
    return stored


def vector_search_pages(
    store: Any,
    provider: EmbeddingProvider,
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    query_text = _normalize_space(query)
    if not query_text:
        return []

    query_embeddings = provider.embed_texts([query_text])
    if not query_embeddings or not query_embeddings[0]:
        return []
    query_vec = query_embeddings[0]

    all_embeddings = store.list_embeddings(target_type="page", limit=1000)
    if not all_embeddings:
        return []

    scored: list[tuple[float, str]] = []
    for emb_row in all_embeddings:
        raw = emb_row.get("embedding")
        if not raw:
            continue
        stored_vec = decode_embedding(raw)
        sim = cosine_similarity(query_vec, stored_vec)
        scored.append((sim, str(emb_row.get("target_id") or "")))

    scored.sort(key=lambda x: -x[0])
    results: list[dict[str, Any]] = []
    for sim, page_id in scored[:max(1, int(limit))]:
        if sim <= 0.0:
            continue
        page = store.get_memory_page(page_id)
        if not page or page.get("status") != "active":
            continue
        result = _page_result(page)
        result["vector_score"] = round(sim, 6)
        results.append(result)
    return results


def _page_embedding_text(page: dict[str, Any]) -> str:
    title = _normalize_space(str(page.get("title") or ""))
    content = _normalize_space(str(page.get("content") or ""))
    return f"{title}\n{content}" if title else content
