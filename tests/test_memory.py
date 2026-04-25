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

    def test_search_returns_directly_linked_active_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, _run_id = _store_with_run(tmp)
            seed_id = store.upsert_memory_page(
                "preferences: python",
                "User prefers pytest for Python tests",
                confidence=0.9,
            )
            linked_id = store.upsert_memory_page(
                "preferences: reporting",
                "User wants concise failure summaries",
                confidence=0.86,
            )
            archived_id = store.upsert_memory_page(
                "archived: old",
                "Old linked memory",
                status="archived",
            )
            store.add_memory_link(seed_id, linked_id, "related", weight=0.8)
            store.add_memory_link(seed_id, archived_id, "related", weight=0.9)

            results = MemoryEngine(store).search("pytest", limit=5)

            linked = [item for item in results if item["type"] == "linked_page"]
            self.assertEqual([item["id"] for item in linked], [linked_id])
            self.assertEqual(linked[0]["relation"], "related")
            self.assertEqual(linked[0]["linked_from"], seed_id)
            self.assertEqual(linked[0]["content"], "User wants concise failure summaries")

    def test_search_returns_reverse_linked_active_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, _run_id = _store_with_run(tmp)
            seed_id = store.upsert_memory_page(
                "preferences: python",
                "User prefers pytest for Python tests",
                confidence=0.9,
            )
            source_id = store.upsert_memory_page(
                "preferences: ci",
                "User expects CI examples",
                confidence=0.82,
            )
            store.add_memory_link(source_id, seed_id, "supports", weight=0.7)

            results = MemoryEngine(store).search("pytest", limit=5)

            linked = [item for item in results if item["type"] == "linked_page"]
            self.assertEqual([item["id"] for item in linked], [source_id])
            self.assertEqual(linked[0]["relation"], "supports")
            self.assertEqual(linked[0]["linked_from"], seed_id)

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

    def test_context_cards_include_compact_association_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, _run_id = _store_with_run(tmp)
            seed_id = store.upsert_memory_page(
                "preferences: python",
                "User prefers pytest for Python tests",
                confidence=0.9,
            )
            linked_id = store.upsert_memory_page(
                "preferences: output",
                "User wants compact test output",
                confidence=0.86,
            )
            store.add_memory_link(seed_id, linked_id, "related", weight=0.8)

            cards = MemoryEngine(store).context_cards("pytest", limit=5)

            linked_cards = [card for card in cards if card["type"] == "linked_page"]
            self.assertEqual(linked_cards[0]["id"], linked_id)
            self.assertEqual(linked_cards[0]["relation"], "related")
            self.assertEqual(linked_cards[0]["linked_from"], seed_id)
            self.assertIn("summary", linked_cards[0])
            self.assertNotIn("content", linked_cards[0])
            self.assertNotIn("evidence", linked_cards[0])

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
            self.assertEqual(result["snapshot"]["page_count"], 1)
            loaded_snapshot = MemoryEngine(store).load_l1_snapshot()
            self.assertIsNotNone(loaded_snapshot)
            self.assertEqual(loaded_snapshot["page_count"], 1)

    def test_dream_consolidate_ingests_model_marked_working_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("memory")
            mission_id = store.create_mission(conversation_id, "memory tests")
            run_id = store.create_run(conversation_id, mission_id, "note")
            note_id = store.add_working_note(
                mission_id,
                run_id,
                "User prefers direct implementation progress",
                metadata={
                    "retention": "memory_candidate",
                    "dimension": "preference",
                    "scope": "global",
                    "confidence": 0.82,
                },
            )

            result = MemoryEngine(store).dream_consolidate(min_confidence=0.7)

            candidate_id = result["w0"]["created"][0]["candidate_id"]
            note = store.list_working_notes(status="candidate_created")[0]
            candidate = store.get_memory_candidate(candidate_id)
            self.assertEqual(result["w0"]["created"][0]["note_id"], note_id)
            self.assertEqual(result["promoted"][0]["candidate_id"], candidate_id)
            self.assertEqual(note["result"], {"candidate_id": candidate_id})
            self.assertEqual(candidate["status"], "promoted")
            self.assertEqual(candidate["evidence"][0]["kind"], "working_note")
            self.assertEqual(candidate["evidence"][0]["id"], note_id)

    def test_working_note_ingestion_skips_ephemeral_and_short_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.initialize()
            conversation_id = store.create_conversation("memory")
            mission_id = store.create_mission(conversation_id, "memory tests")
            run_id = store.create_run(conversation_id, mission_id, "note")
            ephemeral_id = store.add_working_note(
                mission_id,
                run_id,
                "Temporary scratchpad context",
                metadata={"retention": "ephemeral"},
            )
            short_id = store.add_working_note(
                mission_id,
                run_id,
                "tiny",
                metadata={"retention": "memory_candidate"},
            )

            result = MemoryEngine(store).dream_consolidate()

            skipped = {item["note_id"]: item["status"] for item in result["w0"]["skipped"]}
            self.assertEqual(result["w0"]["created"], [])
            self.assertEqual(skipped[ephemeral_id], "skipped:ephemeral")
            self.assertEqual(skipped[short_id], "skipped:too_short")
            self.assertEqual(store.list_memory_candidates(status=None), [])

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

    def test_duplicate_candidate_reinforces_existing_page_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            page_id = store.upsert_memory_page(
                "preferences: updates",
                "User prefers concise updates",
                confidence=0.7,
            )
            duplicate_id = store.add_memory_candidate(
                run_id,
                "User prefers concise updates",
                dimension="preferences",
                confidence=0.82,
            )

            result = MemoryEngine(store).dream_consolidate(min_confidence=0.7)

            page = store.get_memory_page(page_id)
            links = store.list_memory_links(duplicate_id)
            self.assertEqual(result["rejected"][0]["candidate_id"], duplicate_id)
            self.assertEqual(result["rejected"][0]["status"], "rejected:duplicate")
            self.assertGreater(page["confidence"], 0.82)
            self.assertEqual(links[0]["relation"], "reinforces")
            self.assertEqual(links[0]["target_id"], page_id)

    def test_conflicting_candidate_is_routed_to_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, run_id = _store_with_run(tmp)
            page_id = store.upsert_memory_page(
                "preferences: updates",
                "User prefers concise updates",
                confidence=0.9,
            )
            conflict_id = store.add_memory_candidate(
                run_id,
                "User dislikes concise updates",
                dimension="preferences",
                confidence=0.95,
            )

            result = MemoryEngine(store).dream_consolidate(min_confidence=0.7)

            candidate = store.get_memory_candidate(conflict_id)
            links = store.list_memory_links(conflict_id)
            self.assertEqual(result["conflicts"][0]["candidate_id"], conflict_id)
            self.assertEqual(result["conflicts"][0]["conflict_page_id"], page_id)
            self.assertEqual(candidate["status"], "needs_review:conflict")
            self.assertEqual(links[0]["relation"], "conflicts_with")
            self.assertEqual(links[0]["target_id"], page_id)
            self.assertEqual(store.get_memory_page(page_id)["content"], "User prefers concise updates")

    def test_compile_l1_snapshot_writes_compact_active_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, _run_id = _store_with_run(tmp)
            engine = MemoryEngine(store)
            self.assertIsNone(engine.load_l1_snapshot())
            page_id = store.upsert_memory_page(
                "preferences: update style",
                "User prefers direct updates " + ("with compact status notes " * 20),
                scope="global",
                confidence=0.91,
            )
            store.upsert_memory_page(
                "archived: stale",
                "This page should not appear",
                status="archived",
            )

            snapshot = engine.compile_l1_snapshot(limit=10)

            path = store.state_dir / "wiki" / "l1-memory-snapshot.json"
            loaded = engine.load_l1_snapshot()
            self.assertTrue(path.exists())
            self.assertEqual(snapshot["kind"], "l1_memory_snapshot")
            self.assertEqual(snapshot["page_count"], 1)
            self.assertEqual(snapshot["items"][0]["id"], page_id)
            self.assertLessEqual(len(snapshot["items"][0]["summary"]), 183)
            self.assertNotIn("This page should not appear", str(snapshot))
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["page_count"], 1)
            path.write_text("{", encoding="utf-8")
            self.assertIsNone(engine.load_l1_snapshot())


def _store_with_run(tmp: str) -> tuple[StateStore, str]:
    store = StateStore(tmp)
    store.initialize()
    conversation_id = store.create_conversation("memory")
    mission_id = store.create_mission(conversation_id, "memory tests")
    run_id = store.create_run(conversation_id, mission_id, "remember")
    return store, run_id


if __name__ == "__main__":
    unittest.main()
