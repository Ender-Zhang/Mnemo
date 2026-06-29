#!/usr/bin/env python3
"""One-off repair for stable pages contaminated with more than one user's facts.

Older builds merged a candidate into any same-dimension/topic page regardless of
scope, so a single page could accumulate "用户a … 用户b …". Promotion is now
scope-isolated, but pages already merged across users must be repaired.

This finds them by provenance (a page whose source candidates span more than one
scope). By default it only reports. With --apply it resets each such page's
source candidates back to draft and deletes the contaminated page, so the next
dream re-promotes them into clean per-user pages.

Usage:
    python scripts/repair_cross_user_pages.py [--state-dir DIR] [--apply] [--redream]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mnemo_memory import MemoryClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=None, help="memory state dir (defaults to the configured one)")
    parser.add_argument("--apply", action="store_true", help="actually repair (default: report only)")
    parser.add_argument("--redream", action="store_true", help="after --apply, run a local dream to re-form pages now")
    args = parser.parse_args(argv)

    client = MemoryClient(state_dir=args.state_dir) if args.state_dir else MemoryClient()
    report = client.repair_cross_scope_pages(apply=args.apply)

    print(f"scanned {report['scanned_pages']} active pages; "
          f"{report['contaminated_count']} contaminated with multiple users.")
    for page in report["pages"]:
        flag = "repaired" if page["repaired"] else "found"
        print(f"  [{flag}] {page['page_id']} (scope={page['page_scope']}) "
              f"mixes scopes {page['scopes']}")
        print(f"           {page['content_preview']!r}")
        if page["repaired"]:
            print(f"           reset {len(page['reset_candidates'])} candidate(s) to draft")

    if not args.apply and report["contaminated_count"]:
        print("\nRun again with --apply to repair (and --redream to re-form pages immediately).")
        return 0

    if args.apply and args.redream and report["contaminated_count"]:
        print("\nre-forming pages via a local dream ...")
        client.dream_run(use_provider=False)
        print("done; check the memory preview per user.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
