#!/usr/bin/env python3
"""Wipe ALL saved memories for a clean slate (keeps your config).

Clears every event, candidate, stable page, link, tombstone, plan, embedding,
wiki file, L1 snapshot, and dream report from a memory state dir. It does NOT
touch config.json (provider keys, tuning, auto-dream settings stay intact).

This is destructive. By default it only reports what it would delete; it makes a
timestamped backup of state.db and requires --yes to actually wipe.

IMPORTANT: stop your `mnemo-memory serve` process first — wiping the database
out from under a running server leaves it writing to a stale file.

Recommended workflow:

  # 1) Dry run — show how much is stored, delete nothing.
  python scripts/wipe_memory.py

  # 2) Wipe — backs up state.db first, then clears all memory data.
  python scripts/wipe_memory.py --yes

  # 3) Wipe without the safety backup (you really don't want it kept).
  python scripts/wipe_memory.py --yes --no-backup

Options:
  --state-dir DIR   Memory state dir to wipe. Omit to use the configured one
                    (the same state dir your `mnemo-memory serve` process uses).
  --yes             Actually wipe. Without it the script only reports.
  --no-backup       Skip the state.db backup that is made by default.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mnemo_memory import MemoryClient

# Everything in the state dir is regenerable memory data EXCEPT these.
_KEEP = {"config.json"}


def _counts(state_dir: Path) -> dict[str, int]:
    if not (state_dir / "state.db").exists():
        return {"pages": 0, "candidates": 0}
    store = MemoryClient(state_dir=str(state_dir))._store()
    return {
        "pages": len(store.list_memory_pages(status=None, limit=10**9)),
        "candidates": len(store.list_memory_candidates(status=None, limit=10**9)),
    }


def wipe_memory_state(state_dir: str | Path, *, backup: bool = True) -> dict:
    """Remove all memory data under ``state_dir``, preserving config.json.

    Returns a report; the timestamped state.db backup path (if made) is included.
    """
    state = Path(state_dir).expanduser()
    removed: list[str] = []
    backup_path: Path | None = None

    db = state / "state.db"
    if backup and db.exists():
        backup_path = db.with_name(f"state.db.backup-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(db, backup_path)

    # sqlite db + its WAL/SHM sidecars
    for name in ("state.db", "state.db-wal", "state.db-shm"):
        target = state / name
        if target.exists():
            target.unlink()
            removed.append(name)

    # derived/regenerable trees: wiki (pages + L1 snapshot), runs (reports, logs)
    for sub in ("wiki", "runs"):
        directory = state / sub
        if not directory.exists():
            continue
        for child in directory.iterdir():
            if child.name in _KEEP:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        removed.append(f"{sub}/*")

    return {"state_dir": str(state), "removed": removed, "backup": str(backup_path) if backup_path else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=None, help="memory state dir (defaults to the configured one)")
    parser.add_argument("--yes", action="store_true", help="actually wipe (default: report only)")
    parser.add_argument("--no-backup", action="store_true", help="skip the state.db backup made by default")
    args = parser.parse_args(argv)

    client = MemoryClient(state_dir=args.state_dir) if args.state_dir else MemoryClient()
    state_dir = Path(client.state_dir)
    counts = _counts(state_dir)

    print(f"state dir: {state_dir}")
    print(f"stored: {counts['pages']} stable pages, {counts['candidates']} candidates "
          f"(plus their events / links / tombstones / plans / embeddings).")
    print("config.json will be preserved.")

    if not args.yes:
        print("\nDry run — nothing deleted. Re-run with --yes to wipe "
              "(stop `mnemo-memory serve` first).")
        return 0

    report = wipe_memory_state(state_dir, backup=not args.no_backup)
    if report["backup"]:
        print(f"\nbacked up database to: {report['backup']}")
    print(f"removed: {', '.join(report['removed']) or '(nothing — already empty)'}")
    print("done. all memories cleared; config kept. restart `mnemo-memory serve` for a fresh slate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
