# Implement Event Outbox

## Goal
Add a lightweight SQLite event outbox so future daemon, queue, UI replay, and external delivery code can reliably consume persisted state changes without coupling directly to runtime internals.

## Requirements
- Add an `event_outbox` table through the migration system.
- Mirror every `run_events` append into a pending outbox event in the same transaction.
- Add storage APIs to enqueue, list, and mark outbox events.
- Keep outbox payloads structured JSON and compact enough for downstream consumers.
- Preserve current `RunLedger` and runtime behavior.
- Update database spec, checklist, and Trellis task state.

## Acceptance Criteria
- [x] Fresh initialization includes `event_outbox` and schema version advances.
- [x] `append_event()` creates a pending outbox event with matching run id, seq, event type, and payload.
- [x] Manual `enqueue_outbox_event()` works for non-run topics.
- [x] `list_outbox_events()` returns available pending events in deterministic order.
- [x] `mark_outbox_event()` can mark events as sent or failed and records attempts/errors.
- [x] Full tests pass.
- [x] Git is committed and pushed.

## Technical Notes
- Keep this local and minimal; no daemon implementation in this task.
- Use one SQLite transaction for run event + outbox mirror.
- This should be an infrastructure capability, not a model workflow.
