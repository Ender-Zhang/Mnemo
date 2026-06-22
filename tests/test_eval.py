from __future__ import annotations

import contextlib
import tempfile
import unittest


class EvalHarnessTests(unittest.TestCase):
    def test_recall_meets_threshold(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.eval import load_golden, run_recall_eval, seed_corpus

        golden = load_golden()
        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            seed_corpus(client, golden["recall_cases"]["corpus"])
            report = run_recall_eval(client, golden["recall_cases"])

        self.assertGreaterEqual(report["recall_at_k"], 0.75, report)

    def test_promotion_gate_meets_threshold(self) -> None:
        from mnemo_memory import MemoryClient
        from mnemo_memory.eval import load_golden, run_promotion_eval

        golden = load_golden()
        with contextlib.ExitStack() as stack:
            def make_client():
                tmp = stack.enter_context(tempfile.TemporaryDirectory())
                return MemoryClient(state_dir=tmp)

            report = run_promotion_eval(make_client, golden["promotion_cases"])

        self.assertGreaterEqual(report["accuracy"], 0.75, report)


if __name__ == "__main__":
    unittest.main()
