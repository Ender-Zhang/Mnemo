from __future__ import annotations

import math
import tempfile
import unittest


class FakeMaintainer:
    """Records each propose_actions call and promotes every candidate it sees."""

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def propose_actions(self, *, delta, plan):
        candidates = delta.get("memory_candidates", [])
        self.batch_sizes.append(len(candidates))
        return [
            {"tool": "memory_promote_candidate", "candidate_id": c["id"]}
            for c in candidates
        ]


def _seed_draft_candidates(client, count: int) -> None:
    client.update(
        facts=[
            {
                "claim": f"User prefers workflow option number {i} for daily planning.",
                "dimension": "preferences",
                "confidence": 0.9,
            }
            for i in range(count)
        ],
        source="unit-test",
    )


class DreamBatchingTests(unittest.TestCase):
    def test_default_dream_batch_config(self) -> None:
        from mnemo_memory.core.config import ConfigOverrides, resolve_memory_config

        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_memory_config(ConfigOverrides(state_dir=tmp))
            self.assertEqual(config.dream_batch_size, 8)
            self.assertEqual(config.dream_max_batches, 6)

    def test_dream_batch_config_resolves_from_env(self) -> None:
        from mnemo_memory.core.config import ConfigOverrides, resolve_memory_config

        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_memory_config(
                ConfigOverrides(state_dir=tmp),
                env={
                    "MNEMO_MEMORY_DREAM_BATCH_SIZE": "4",
                    "MNEMO_MEMORY_DREAM_MAX_BATCHES": "3",
                },
            )
            self.assertEqual(config.dream_batch_size, 4)
            self.assertEqual(config.dream_max_batches, 3)

    def test_model_dream_splits_candidates_into_batches(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.sdk.client import _propose_dream_actions_batched

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_draft_candidates(client, 20)
            engine = client._engine()
            delta = engine.collect_dream_delta(limit=50)
            total = len(delta["memory_candidates"])
            self.assertGreater(total, 5, "need enough candidates to force batching")

            fake = FakeMaintainer()
            actions, calls = _propose_dream_actions_batched(
                engine, fake, delta, limit=50, advanced_dreaming=False,
                batch_size=5, max_batches=10,
            )

            self.assertEqual(calls, math.ceil(total / 5))
            self.assertTrue(all(size <= 5 for size in fake.batch_sizes))
            # Every candidate gets exactly one (de-duplicated) promote action.
            ids = [a["candidate_id"] for a in actions]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(len(ids), total)

    def test_model_dream_caps_batches(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.sdk.client import _propose_dream_actions_batched

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_draft_candidates(client, 20)
            engine = client._engine()
            delta = engine.collect_dream_delta(limit=50)

            fake = FakeMaintainer()
            _, calls = _propose_dream_actions_batched(
                engine, fake, delta, limit=50, advanced_dreaming=False,
                batch_size=5, max_batches=2,
            )
            self.assertEqual(calls, 2)

    def test_small_backlog_stays_single_call(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.sdk.client import _propose_dream_actions_batched

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_draft_candidates(client, 3)
            engine = client._engine()
            delta = engine.collect_dream_delta(limit=50)

            fake = FakeMaintainer()
            _, calls = _propose_dream_actions_batched(
                engine, fake, delta, limit=50, advanced_dreaming=False,
                batch_size=8, max_batches=6,
            )
            self.assertEqual(calls, 1)

    def test_dream_maintenance_records_model_calls(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            _seed_draft_candidates(client, 2)
            engine = client._engine()
            engine.dream_maintenance(limit=10, deterministic_fallback=True, model_calls=4)

            status = client.dream_status()
            self.assertEqual(status["latest"]["model_calls"], 4)


if __name__ == "__main__":
    unittest.main()
