from __future__ import annotations

import tempfile
import unittest

from mnemo.memory import MemoryEngine
from mnemo.storage import StateStore


class MemoryEngineTests(unittest.TestCase):
    def test_promote_candidate_creates_page_and_marks_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            candidate_id = store.add_memory_candidate(
                run_id,
                "User prefers concise engineering updates",
                dimension="preferences",
                confidence=0.82,
            )

            result = MemoryEngine(store).promote_candidate(candidate_id)

            self.assertEqual(result["status"], "promoted")
            candidate = store.get_memory_candidate(candidate_id)
            page = store.get_memory_page(result["page_id"])
            links = store.list_memory_links(candidate_id)
            self.assertEqual(candidate["status"], "promoted")
            self.assertEqual(page["content"], "User prefers concise engineering updates")
            self.assertEqual(page["source_candidate_id"], candidate_id)
            self.assertEqual(links[0]["target_id"], result["page_id"])

    def test_reject_candidate_records_reason_in_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            candidate_id = store.add_memory_candidate(run_id, "Temporary fact")

            result = MemoryEngine(store).reject_candidate(candidate_id, "not durable")

            self.assertEqual(result["status"], "rejected:not_durable")
            self.assertEqual(store.get_memory_candidate(candidate_id)["status"], "rejected:not_durable")

    def test_search_returns_pages_and_candidates_with_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            candidate_id = store.add_memory_candidate(
                run_id,
                "User uses pytest for Python tests",
                dimension="preferences",
                confidence=0.75,
            )
            page_id = store.upsert_memory_page(
                "preferences: testing",
                "User prefers pytest assertions",
                confidence=0.9,
            )

            results = MemoryEngine(store).search("pytest", limit=10)

            typed_ids = {(result["type"], result["id"]) for result in results}
            self.assertIn(("page", page_id), typed_ids)
            self.assertIn(("candidate", candidate_id), typed_ids)

    def test_context_cards_are_compact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            store.add_memory_candidate(
                run_id,
                "User prefers very compact context cards for model prompts",
                dimension="preferences",
                confidence=0.75,
            )

            cards = MemoryEngine(store).context_cards("compact context", limit=5)

            self.assertEqual(cards[0]["type"], "candidate")
            self.assertIn("summary", cards[0])
            self.assertNotIn("evidence", cards[0])

    def test_dream_consolidate_promotes_confident_drafts_and_skips_low_confidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            high_id = store.add_memory_candidate(
                run_id,
                "User values local-first tools",
                confidence=0.8,
            )
            low_id = store.add_memory_candidate(
                run_id,
                "User may like dashboards",
                confidence=0.4,
            )

            result = MemoryEngine(store).dream_consolidate(min_confidence=0.7)

            self.assertEqual([item["candidate_id"] for item in result["promoted"]], [high_id])
            self.assertEqual([item["candidate_id"] for item in result["skipped"]], [low_id])
            self.assertEqual(store.get_memory_candidate(high_id)["status"], "promoted")
            self.assertEqual(store.get_memory_candidate(low_id)["status"], "draft")

    def test_dream_consolidate_rejects_empty_and_duplicate_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            empty_id = store.add_memory_candidate(run_id, "   ", confidence=0.95)
            first_id = store.add_memory_candidate(
                run_id,
                "User prefers direct updates",
                confidence=0.95,
            )
            duplicate_id = store.add_memory_candidate(
                run_id,
                "User prefers direct updates",
                confidence=0.95,
            )

            result = MemoryEngine(store).dream_consolidate(min_confidence=0.7)

            rejected = {item["candidate_id"]: item["status"] for item in result["rejected"]}
            self.assertEqual(store.get_memory_candidate(first_id)["status"], "promoted")
            self.assertEqual(rejected[empty_id], "rejected:empty")
            self.assertEqual(rejected[duplicate_id], "rejected:duplicate")


def _store_with_run(tmp: str) -> tuple[StateStore, str]:
    store = StateStore(tmp)
    store.initialize()
    conversation_id = store.create_conversation("memory")
    mission_id = store.create_mission(conversation_id, "memory tests")
    run_id = store.create_run(conversation_id, mission_id, "remember")
    return store, run_id


if __name__ == "__main__":
    unittest.main()
