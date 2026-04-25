# Fix Web Stop Active Run Target

## Goal

Prevent the web Stop control from cancelling the previous run when a new turn has started but the current stream has not emitted its first event yet.

## Requirements

- Track a volatile `activeRunId` for the currently streaming run.
- Keep durable `lastRunId` only for replay/resume.
- Disable the Stop control until the active stream exposes the current `run_id`.
- Send `/api/runs/cancel` with `activeRunId`, never `lastRunId`.
- Clear `activeRunId` when the active stream finishes or reset is clicked.
- Update frontend state-management spec and web asset regression checks.

## Acceptance Criteria

- [x] `requestCancel()` targets `state.activeRunId`.
- [x] `updateComposerState()` enables Stop only when `state.activeRunId` exists.
- [x] `runTurn()` clears stale `activeRunId` before starting a new request.
- [x] `persistEventEnvelope()` assigns `activeRunId` only while busy and receiving the active stream.
- [x] Focused web tests pass.
- [x] Full unit tests pass.
- [x] Trellis task validation passes.
- [x] Changes are committed locally.

## Technical Notes

- Do not add another persistent localStorage key for `activeRunId`; it is turn-scoped runtime state.
- Keep the frontend single-composer interaction model.
