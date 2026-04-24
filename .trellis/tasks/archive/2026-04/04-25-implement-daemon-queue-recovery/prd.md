# Implement Daemon Queue Recovery

## Goal
Add a lightweight persisted execution queue so Mnemo can accept work, process it with a single worker instance, report status, and recover stale running jobs after interruption.

## Requirements
- Persist queued run requests in SQLite.
- Provide a simple daemon runner that drains queued jobs through the existing runtime path.
- Prevent concurrent daemon workers for the same state directory with a local lock.
- Requeue stale running jobs before processing.
- Add CLI commands for enqueue, run, status, and recovery.
- Keep the design lightweight and avoid a new workflow engine.

## Acceptance
- [x] `StateStore` has queue APIs for enqueue, list, claim, complete, recover, and stats.
- [x] SQLite migrations create the queue schema and remain idempotent.
- [x] Daemon runner processes pending jobs through `RunRequest`.
- [x] Single-instance lock blocks a second worker for the same state directory.
- [x] CLI supports `mnemo daemon enqueue`, `run`, `status`, and `recover`.
- [x] Stale running jobs can be recovered to pending.
- [x] Tests cover storage lifecycle, daemon runner, lock, and CLI commands.
- [x] Implementation checklist and backend storage specs are updated.
- [x] Changes are committed and pushed.
