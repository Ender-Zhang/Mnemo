from __future__ import annotations

import tempfile
import unittest


def _seed_two_users(client) -> None:
    rows = [
        ("Prefers a teal accent in the UI.", "preferences", "user:alice"),
        ("Prefers a crimson accent in the UI.", "values", "user:bob"),
    ]
    for claim, dimension, scope in rows:
        update = client.update(facts=[{"claim": claim, "dimension": dimension, "scope": scope, "confidence": 0.9}], source="test")
        client.force_promote_candidate(update["memory_candidates"][0]["candidate_id"])


class RecallScopeTests(unittest.TestCase):
    def test_search_scoped_by_uid(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_two_users(client)

            scoped = {m.get("scope") for m in client.search("accent", uid="alice")["matches"]}
            self.assertIn("user:alice", scoped)
            self.assertNotIn("user:bob", scoped)

            everyone = {m.get("scope") for m in client.search("accent")["matches"]}
            self.assertIn("user:alice", everyone)
            self.assertIn("user:bob", everyone)

    def test_known_uids_lists_distinct_users(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_two_users(client)
            self.assertEqual(client.known_uids()["uids"], ["alice", "bob"])

    def test_recall_and_context_scoped_by_uid(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_two_users(client)

            recall_scopes = {item.get("scope") for item in client.recall("accent", uid="alice")["items"]}
            self.assertNotIn("user:bob", recall_scopes)

            context_scopes = {card.get("scope") for card in client.context("accent", uid="alice")["cards"] if card.get("scope")}
            self.assertNotIn("user:bob", context_scopes)


if __name__ == "__main__":
    unittest.main()
