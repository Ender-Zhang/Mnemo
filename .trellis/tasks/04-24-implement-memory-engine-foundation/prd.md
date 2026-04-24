# Implement Memory Engine Foundation

## Goal

Move Mnemo memory beyond draft candidates by adding stable memory pages, candidate review operations, associative recall, and a lightweight DreamCycle that can consolidate memory during idle time.

## Requirements

- Add stable memory page persistence in SQLite.
- Add memory links/indexes to support associative recall.
- Add memory engine service for:
  - proposing candidates,
  - promoting candidates into pages,
  - rejecting candidates,
  - searching stable pages and candidates together,
  - running deterministic DreamCycle consolidation.
- Keep normal task tools from directly mutating stable memory except through explicit promotion/consolidation APIs.
- Add CLI commands to inspect memory and run dream consolidation.
- Persist memory lifecycle events to RunLedger when a run id is present.
- Add tests for promotion, rejection, stable search, DreamCycle, and CLI memory commands.

## Acceptance Criteria

- `mnemo memory search <query>` returns stable memory pages and draft candidates.
- `mnemo memory promote <candidate_id>` creates or updates a stable memory page and marks the candidate promoted.
- `mnemo dream run` promotes high-confidence draft candidates deterministically.
- Existing memory candidate tools continue to work.
- Tests pass without network access.
