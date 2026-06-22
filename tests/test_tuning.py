from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


_GOOD_FACT = {
    "claim": "User codes primarily in Python and uses pytest for testing.",
    "dimension": "cognition",
    "confidence": 0.9,
}


class TuningConfigTests(unittest.TestCase):
    def test_tuning_config_roundtrip(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            default = client.tuning_config()
            self.assertAlmostEqual(default["quality_write_threshold"], 0.68)
            self.assertAlmostEqual(default["promote_min_confidence"], 0.7)

            saved = client.save_tuning_config(quality_write_threshold=0.8, promote_min_confidence=0.6)
            self.assertAlmostEqual(saved["quality_write_threshold"], 0.8)
            self.assertAlmostEqual(saved["promote_min_confidence"], 0.6)
            raw = json.loads((Path(tmp) / "config.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(raw["quality_write_threshold"], 0.8)

    def test_strict_quality_threshold_rejects_at_promote(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            # Impossibly strict bands: even a decent claim becomes low-quality at write time.
            client.save_tuning_config(quality_write_threshold=0.99, quality_draft_threshold=0.98)
            update = client.update(facts=[_GOOD_FACT], source="eval")
            review = client.promote_candidate(update["memory_candidates"][0]["candidate_id"])
            self.assertEqual(review.get("decision"), "rejected")

    def test_configured_min_confidence_default_applies(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            client.save_tuning_config(promote_min_confidence=0.95)
            update = client.update(facts=[_GOOD_FACT], source="eval")
            # No explicit min_confidence -> uses the configured 0.95; the 0.9 candidate is skipped.
            review = client.promote_candidate(update["memory_candidates"][0]["candidate_id"])
            self.assertEqual(review.get("decision"), "skipped")


if __name__ == "__main__":
    unittest.main()
