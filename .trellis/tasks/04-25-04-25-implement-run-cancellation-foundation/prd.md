# Implement Run Cancellation Foundation

## Goal

Add a lightweight explicit cancellation foundation so runs and queued jobs can be marked cancelled durably, and active runtimes can stop between provider/tool steps without introducing workflow routing.

## Requirements

- Add `cancelled` as a persisted run/queue status.
- Add storage APIs to read/cancel runs and cancel queued work.
- Add CLI commands to cancel a run or queued daemon item.
- Make local/provider runtimes check cancellation between interruptible steps.
- Keep cancellation compact in ledger/chat events and avoid treating it as provider/tool failure.
- Update database/error-handling specs and implementation checklist.

## Acceptance Criteria

- [x] `StateStore.cancel_run(...)` marks running runs cancelled and is idempotent for terminal runs.
- [x] `StateStore.cancel_queue_item(...)` prevents pending queued work from being claimed.
- [x] `mnemo runs cancel <run_id>` records a cancellation request.
- [x] `mnemo daemon cancel <queue_id>` cancels queued work.
- [x] Provider runtime completes with `status="cancelled"` when cancellation is observed between steps.
- [x] Focused and full unit tests pass.
- [x] Trellis task validation passes.
- [x] Changes are committed locally.

## Technical Notes

- Cancellation is cooperative: blocking provider calls still rely on timeout, then runtime observes cancellation.
- Do not add a workflow router; cancellation is a runtime/state capability.
