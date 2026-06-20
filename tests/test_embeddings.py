from __future__ import annotations

import tempfile
import unittest


class _FakeEmbeddingProvider:
    """Deterministic bag-of-words embedding over a fixed vocab (no network)."""

    VOCAB = ["python", "rust", "coffee", "tea", "concise", "verbose", "progress"]

    def __init__(self) -> None:
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[1.0 if word in text.lower() else 0.0 for word in self.VOCAB] for text in texts]


def _seed_two_pages(client) -> None:
    for claim, dimension in [
        ("User writes a lot of Python code daily.", "cognition"),
        ("User loves coffee in the morning.", "preferences"),
    ]:
        update = client.update(facts=[{"claim": claim, "dimension": dimension, "confidence": 0.9}], source="test")
        client.force_promote_candidate(update["memory_candidates"][0]["candidate_id"])


class EmbeddingSearchTests(unittest.TestCase):
    def test_vector_search_and_incremental_index(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.memory.embedding import ensure_page_embeddings, vector_search_pages

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_two_pages(client)
            store = client._store()
            provider = _FakeEmbeddingProvider()
            pages = store.list_memory_pages(status="active", limit=10)
            self.assertGreaterEqual(len(pages), 2)

            indexed = ensure_page_embeddings(store, provider, pages, "fake")
            self.assertEqual(indexed, len(pages))
            # Second pass is incremental: nothing re-embedded.
            self.assertEqual(ensure_page_embeddings(store, provider, pages, "fake"), 0)

            results = vector_search_pages(store, provider, "python", limit=3)
            self.assertTrue(results)
            top = results[0]
            self.assertIn("python", f"{top.get('title', '')} {top.get('content', '')}".lower())
            self.assertIn("vector_score", top)

    def test_engine_search_includes_vector_route(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.memory import MemoryEngine
        from mnemo_memory.memory.embedding import ensure_page_embeddings

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_two_pages(client)
            store = client._store()
            provider = _FakeEmbeddingProvider()
            ensure_page_embeddings(store, provider, store.list_memory_pages(status="active", limit=10), "fake")

            engine = MemoryEngine(store, embedding_provider=provider, embedding_model="fake")
            result = engine.search_with_plan("python", limit=5, search_scope="memory")
            routes = {signal.get("route") for match in result["matches"] for signal in match.get("match_signals", [])}
            self.assertIn("vector", routes)

    def test_embedding_config_roundtrip_and_status(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.interfaces.web import dispatch_memory_api

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_two_pages(client)

            saved = dispatch_memory_api(
                client,
                "save-embedding-config",
                {"enabled": True, "base_url": "http://emb.local/v1", "model": "emb-1"},
            )
            self.assertTrue(saved["enabled"])
            self.assertTrue(saved["configured"])

            loaded = dispatch_memory_api(client, "embedding-config", {})
            self.assertEqual(loaded["model"], "emb-1")

            status = dispatch_memory_api(client, "embedding-status", {})
            self.assertEqual(status["active_count"], 2)
            self.assertEqual(status["indexed_count"], 0)
            self.assertEqual(status["stale_count"], 2)

    def test_reindex_requires_config(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            with self.assertRaises(ValueError):
                client.reindex_embeddings()


if __name__ == "__main__":
    unittest.main()
