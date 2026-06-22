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

    def test_l0_entries_carry_page_id(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_two_users(client)
            entries = client.profile()["entries"]
            self.assertTrue(entries)
            for entry in entries:
                self.assertTrue(entry["page_id"].startswith("mempg_"))
                # the page_id must be traceable back to an event via provenance
                self.assertTrue(client.provenance(entry["page_id"])["events"])

    def test_event_flow_scoped_by_uid(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_two_users(client)

            everyone = client.event_flow()["flows"]
            self.assertGreaterEqual(len(everyone), 2)

            alice = client.event_flow(uid="alice")
            self.assertTrue(alice["flows"])
            scopes = {flow["event"]["scope"] for flow in alice["flows"]}
            for flow in alice["flows"]:
                scopes.update(candidate.get("scope") for candidate in flow["candidates"])
            self.assertIn("user:alice", scopes)
            self.assertNotIn("user:bob", scopes)

            # the chain is event -> promoted candidate -> page (traceable downstream)
            chained = [
                flow for flow in alice["flows"]
                if any(candidate.get("page_ids") for candidate in flow["candidates"])
            ]
            self.assertTrue(chained, "expected at least one event linked through to a page")

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
