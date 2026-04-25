# Implement Web Run Cancellation

## Goal

Expose persisted run cancellation in the single-chat web experience so a user can stop the current turn without leaving the composer.

## Requirements

- Add `POST /api/runs/cancel` to cancel a persisted run by `run_id`.
- Record a compact `run.cancel.requested` ledger event from the web endpoint.
- Use a threaded stdlib web server so a cancel request can be processed while `/api/chat` is streaming.
- Add one stop control inside the existing composer; do not add an operations panel or workflow UI.
- Keep streaming behavior intact: the client should request cancellation and continue reading until the runtime emits completion/error.
- Keep event replay/localStorage continuity unchanged.
- Update backend/frontend specs and checklist.

## Acceptance Criteria

- [x] Web server processes concurrent request handlers.
- [x] `POST /api/runs/cancel` returns JSON `{run_id,status,changed}` for valid runs.
- [x] Missing or unknown `run_id` returns the appropriate JSON error.
- [x] Web client includes a busy-state stop control that calls `/api/runs/cancel`.
- [x] Cancel UI does not clear conversation, mission, run, or replay state.
- [x] Focused and full unit tests pass.
- [x] Trellis task validation passes.
- [x] Changes are committed locally.

## Technical Notes

- Cancellation remains cooperative: provider calls may only observe it after a model call returns or times out.
- The frontend should not abort the streaming response after requesting cancellation, otherwise it can miss the final `run.completed` event.
