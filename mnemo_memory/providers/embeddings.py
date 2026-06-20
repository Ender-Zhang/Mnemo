from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error, request

from ..core.config import MemoryConfig
from ..core.jsonutil import dumps
from ..core.log import get_logger, log_event

_LOG = get_logger("embeddings")


class OpenAICompatibleEmbeddingProvider:
    """EmbeddingProvider backed by an OpenAI-compatible ``/embeddings`` endpoint.

    Configured independently from the maintenance/chat provider via
    ``embedding_base_url`` / ``embedding_model`` / ``embedding_api_key`` so users
    can host embeddings elsewhere. Implements the ``EmbeddingProvider`` protocol
    (``embed_texts``) consumed by ``memory/embedding.py``.
    """

    def __init__(self, config: MemoryConfig) -> None:
        if not config.embedding_base_url:
            raise ValueError("embeddings require embedding_base_url")
        if not config.embedding_model:
            raise ValueError("embeddings require embedding_model")
        self.config = config
        self.model = str(config.embedding_model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._post_json("/embeddings", {"model": self.model, "input": list(texts)})
        data = response.get("data")
        if not isinstance(data, list):
            raise ValueError("embeddings provider returned no data array")
        rows: list[tuple[int, list[float]]] = []
        for position, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            vector = item.get("embedding")
            index = item.get("index", position)
            if isinstance(vector, list):
                rows.append((int(index) if isinstance(index, int) else position, [float(value) for value in vector]))
        rows.sort(key=lambda row: row[0])
        return [vector for _, vector in rows]

    def ping(self) -> int:
        """Embed a tiny input to verify the endpoint; returns the vector dimension."""
        vectors = self.embed_texts(["ping"])
        return len(vectors[0]) if vectors and vectors[0] else 0

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = str(self.config.embedding_base_url or "").rstrip("/")
        key = self.config.embedding_api_key
        req = request.Request(
            base + path,
            data=dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {key}"} if key else {}),
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_s) as resp:
                body = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            log_event(_LOG, "embeddings_error", level=logging.WARNING, code=exc.code)
            raise ValueError(f"embeddings provider error {exc.code}: {detail[:240]}") from exc
        except OSError as exc:
            raise ValueError(f"embeddings provider request failed: {exc}") from exc
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("embeddings provider returned non-object JSON")
        return parsed
