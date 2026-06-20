from __future__ import annotations

import tempfile
import unittest


class LoggingTests(unittest.TestCase):
    def test_log_event_formats_structured_fields(self) -> None:
        from mnemo_memory.core.log import get_logger, log_event

        logger = get_logger("test")
        with self.assertLogs("mnemo_memory.test", level="INFO") as captured:
            log_event(logger, "demo_event", candidate_id="mem_1", decision="promoted", score=0.873, note="has space", dropped=None)

        line = captured.output[0]
        self.assertIn("demo_event", line)
        self.assertIn("candidate_id=mem_1", line)
        self.assertIn("decision=promoted", line)
        self.assertIn("score=0.873", line)
        self.assertIn('note="has space"', line)
        self.assertNotIn("dropped", line)

    def test_promote_emits_decision_log(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[{"claim": "User prefers concise progress updates with explicit next steps.", "dimension": "preferences", "confidence": 0.9}],
                source="test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]
            with self.assertLogs("mnemo_memory.learning", level="INFO") as captured:
                client.promote_candidate(candidate_id)

            joined = "\n".join(captured.output)
            self.assertIn("candidate_promote_review", joined)
            self.assertIn(candidate_id, joined)

    def test_reject_emits_decision_log(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            update = client.update(
                facts=[{"claim": "Temporary low-value status note.", "confidence": 0.5}],
                source="test",
            )
            candidate_id = update["memory_candidates"][0]["candidate_id"]
            with self.assertLogs("mnemo_memory.learning", level="INFO") as captured:
                client.reject_candidate(candidate_id, "not_useful")

            self.assertIn("candidate_reject", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
