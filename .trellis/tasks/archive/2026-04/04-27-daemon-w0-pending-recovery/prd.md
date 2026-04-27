# Daemon W0 Pending Recovery

## Goal
Align daemon startup/recovery behavior with the design package by flushing model-marked W0 working notes into memory candidates through the existing MemoryEngine pipeline.

## Requirements
- Daemon recovery must process only W0 working notes explicitly marked with `metadata.retention="memory_candidate"`.
- Recovery must reuse `MemoryEngine.ingest_working_notes()` so candidate safety evidence, statuses, and note lifecycle stay consistent.
- Recovery must not scan or mutate ordinary ephemeral working notes.
- Daemon status should expose a compact W0 pending count for operator and harness inspection.
- CLI JSON payloads must include the new recovery/status data without breaking existing queue fields.

## Acceptance Criteria
- [x] `DaemonRunner.recover()` returns queue recovery plus W0 recovery results.
- [x] `DaemonRunner.drain()` performs the same W0 recovery under the daemon lock before queue work.
- [x] `DaemonRunner.status()` reports pending model-marked W0 count.
- [x] Unit tests cover W0 candidate creation and non-mutating ephemeral notes.
- [x] CLI tests cover JSON payload shape for status/recover.
- [x] Checklist and backend specs reflect the landed behavior.

## Technical Notes
- No new workflow router or rule-based memory classifier is added.
- The daemon only selects already-marked note ids; the model remains the decision owner for what should enter long-term memory.
