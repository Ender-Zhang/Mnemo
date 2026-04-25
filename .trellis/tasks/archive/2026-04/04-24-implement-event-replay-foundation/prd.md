# Implement Event Replay Foundation

## Goal

Make Mnemo runs replayable and resumable by adding a JSONL trace mirror and CLI APIs for reading ChatEvent streams after the fact.

## Requirements

- Mirror every RunLedger event into `state_dir/runs/<run_id>.jsonl`.
- Add RunLedger APIs to load run trace and chat events since a sequence.
- Add CLI `events --since <seq>` and `events --chat` for frontend-style replay.
- Add CLI `replay <run_id>` for deterministic trace summary.
- Preserve existing SQLite event source of truth.
- Add tests for JSONL trace, since filtering, chat event projection, and CLI replay.

## Acceptance Criteria

- Every run writes a JSONL trace file.
- `mnemo events <run_id> --chat --json` returns previously streamed ChatEvents.
- `mnemo events <run_id> --since N --json` filters events.
- Tests pass without network access.
