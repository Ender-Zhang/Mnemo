#!/usr/bin/env python3
"""Model-driven quality eval (opt-in; needs a configured provider; not in CI).

Reuses the deterministic harness (mnemo_memory.eval) against a throwaway state
dir, and additionally exercises the configured provider by letting it extract
memories from raw event text. Recall runs semantically when an embeddings
endpoint is configured.

Run:

  MNEMO_MEMORY_BASE_URL=... MNEMO_MEMORY_MODEL=... MNEMO_MEMORY_API_KEY=... \
    python scripts/eval_model.py

Prints a JSON report; it does not assert thresholds (that is the CI test's job).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mnemo_memory import MemoryClient  # noqa: E402
from mnemo_memory.eval import load_golden, run_promotion_eval, run_recall_eval, seed_corpus  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Model-driven memory eval")
    parser.add_argument("--golden", default=None, help="path to a golden.json (defaults to packaged set)")
    args = parser.parse_args(argv)
    golden = load_golden(args.golden)

    report: dict[str, object] = {}

    with tempfile.TemporaryDirectory() as tmp:
        client = MemoryClient(state_dir=tmp)
        provider = client.provider_config()
        report["provider_configured"] = bool(provider.get("configured"))
        report["embeddings_enabled"] = bool(client.embedding_status().get("enabled"))

        seed_corpus(client, golden["recall_cases"]["corpus"])
        report["recall"] = run_recall_eval(client, golden["recall_cases"])

        if provider.get("configured"):
            produced = 0
            errors: list[str] = []
            events = golden.get("event_cases", [])
            for text in events:
                try:
                    result = client.ingest_event(text=text, source="eval", use_provider=True)
                    if result.get("memory_candidates"):
                        produced += 1
                except Exception as exc:  # noqa: BLE001 - opt-in script surfaces provider errors.
                    errors.append(str(exc))
            report["model_extraction"] = {"events": len(events), "produced_candidate": produced, "errors": errors}
        else:
            report["model_extraction"] = "skipped: no provider configured"

    with contextlib.ExitStack() as stack:
        def make_client() -> MemoryClient:
            case_dir = stack.enter_context(tempfile.TemporaryDirectory())
            return MemoryClient(state_dir=case_dir)

        report["promotion"] = run_promotion_eval(make_client, golden["promotion_cases"])

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
