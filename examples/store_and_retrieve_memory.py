#!/usr/bin/env python3
"""Store a memory candidate, promote it, and retrieve it with search."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mnemo_memory import MemoryClient  # noqa: E402


DEFAULT_STATE_DIR = REPO_ROOT / ".mnemo-memory-example"
DEFAULT_CLAIM = (
    "用户偏好 concise implementation progress updates: summarize completed code changes, "
    "test results, and next steps."
)
DEFAULT_QUERY = "concise implementation progress updates test results next steps"


def main() -> int:
    args = _parse_args()
    client = MemoryClient(state_dir=args.state_dir)

    update = client.update(
        facts=[
            {
                "claim": args.claim,
                "dimension": "preferences",
                "scope": "user:demo",
                "confidence": 0.92,
                "actor": "user",
                "conversation_id": "example-conversation",
                "message_id": "example-message",
                "excerpt": "以后给我代码任务进度时，尽量简洁，只说完成内容、测试结果和下一步。",
            }
        ],
        source="example-script",
        run_id="example-run",
        mission_id="example-mission",
    )
    candidate = _first(update.get("memory_candidates"))
    if not candidate:
        raise RuntimeError(f"no memory candidate was created: {update}")

    review = client.promote_candidate(candidate["candidate_id"], min_confidence=args.min_confidence)
    search = client.search(args.query, scope="memory", limit=5)

    result = {
        "state_dir": str(Path(args.state_dir).expanduser()),
        "created_candidate": candidate,
        "promotion_review": review,
        "search_query": args.query,
        "matches": search.get("matches", []),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Example: store a Mnemo memory candidate, promote it, then retrieve it."
    )
    parser.add_argument(
        "--state-dir",
        default=str(DEFAULT_STATE_DIR),
        help="Memory state directory. Defaults to .mnemo-memory-example in the repo root.",
    )
    parser.add_argument("--claim", default=DEFAULT_CLAIM, help="Memory claim to store.")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Search query used after promotion.")
    parser.add_argument("--min-confidence", type=float, default=0.7, help="Promotion confidence threshold.")
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON.")
    return parser.parse_args()


def _first(value: Any) -> dict[str, Any] | None:
    return value[0] if isinstance(value, list) and value and isinstance(value[0], dict) else None


def _print_human(result: dict[str, Any]) -> None:
    candidate = result["created_candidate"]
    review = result["promotion_review"]
    matches = result["matches"]

    print(f"State dir: {result['state_dir']}")
    print(f"Created candidate: {candidate['candidate_id']} ({candidate['status']})")
    print(f"Promotion decision: {review.get('decision') or review.get('status')}")
    if review.get("page_id"):
        print(f"Stable page: {review['page_id']}")

    print(f"Search query: {result['search_query']}")
    if not matches:
        print("No matches found.")
        return

    print("Matches:")
    for index, item in enumerate(matches, start=1):
        title = item.get("title") or item.get("claim") or item.get("content") or item.get("id")
        score = item.get("retrieval_score", item.get("confidence", "-"))
        print(f"{index}. [{item.get('type')}] {title} (score={score})")


if __name__ == "__main__":
    raise SystemExit(main())
