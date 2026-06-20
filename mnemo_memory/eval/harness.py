"""Quality eval harness for recall and the promotion gate.

The unit tests measure mechanics; this measures *quality*: does the right memory
come back for a query, and does the promotion gate make the right call. The same
scoring is reused by the deterministic CI test (tests/test_eval.py) and the
opt-in, provider-backed script (scripts/eval_model.py).

Decisions are scored at a coarse granularity (accepted / rejected / deferred) so
the eval flags real regressions without being brittle to minor wording changes in
gate sub-reasons.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

GOLDEN_PATH = Path(__file__).with_name("golden.json")


def load_golden(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else GOLDEN_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("golden dataset must be a JSON object")
    return data


def seed_corpus(client: Any, corpus: list[dict[str, Any]]) -> list[str]:
    """Force-promote each fact into a stable page (bypasses the gate on purpose)."""
    page_ids: list[str] = []
    for fact in corpus:
        update = client.update(facts=[fact], source="eval")
        candidate_id = update["memory_candidates"][0]["candidate_id"]
        result = client.force_promote_candidate(candidate_id)
        if result.get("page_id"):
            page_ids.append(str(result["page_id"]))
    return page_ids


def run_recall_eval(client: Any, recall_cases: dict[str, Any]) -> dict[str, Any]:
    k = int(recall_cases.get("k", 5))
    queries = recall_cases.get("queries", [])
    hits = 0
    reciprocal = 0.0
    details: list[dict[str, Any]] = []
    for case in queries:
        query = str(case.get("query", ""))
        needle = str(case.get("expect_contains", "")).lower()
        result = client.search(query, limit=k)
        matches = result.get("matches", []) if isinstance(result, dict) else []
        rank = None
        for position, match in enumerate(matches[:k], start=1):
            haystack = f"{match.get('title', '')} {match.get('content', '')} {match.get('claim', '')}".lower()
            if needle and needle in haystack:
                rank = position
                break
        if rank is not None:
            hits += 1
            reciprocal += 1.0 / rank
        details.append({"query": query, "rank": rank})
    count = max(1, len(queries))
    return {
        "recall_at_k": round(hits / count, 4),
        "mrr": round(reciprocal / count, 4),
        "k": k,
        "count": len(queries),
        "details": details,
    }


def coarse_decision(result: dict[str, Any]) -> str:
    decision = str(result.get("decision") or "").lower()
    status = str(result.get("status") or "").lower()
    text = decision or status
    if "promoted" in text:
        return "accepted"
    if text.startswith("rejected") or "reject" in decision:
        return "rejected"
    return "deferred"


def run_promotion_eval(make_client: Callable[[], Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Score promotion-gate decisions. Each case runs on a fresh client/state so
    earlier promotions never leak into later duplicate/conflict checks."""
    correct = 0
    details: list[dict[str, Any]] = []
    for case in cases:
        client = make_client()
        for seed in case.get("seed", []) or []:
            seeded = client.update(facts=[seed], source="eval")
            client.promote_candidate(seeded["memory_candidates"][0]["candidate_id"])
        update = client.update(facts=[case["fact"]], source="eval")
        candidate_id = update["memory_candidates"][0]["candidate_id"]
        result = client.promote_candidate(candidate_id)
        got = coarse_decision(result)
        expected = case.get("expect")
        accepted = expected if isinstance(expected, list) else [expected]
        ok = got in accepted
        correct += 1 if ok else 0
        details.append({"name": case.get("name"), "got": got, "expected": accepted, "ok": ok})
    count = max(1, len(cases))
    return {"accuracy": round(correct / count, 4), "count": len(cases), "details": details}
