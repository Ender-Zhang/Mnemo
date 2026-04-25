# Guard Web Reset During Active Run

## Goal

Prevent the single-chat UI from clearing durable chat state while a run is still streaming.

## Requirements

- Disable the `New` reset button while `state.busy` is true.
- Guard the reset click handler so it returns without mutating state during an active run.
- Preserve the existing Stop control as the active-run interruption path.
- Update frontend state spec and asset tests.

## Acceptance Criteria

- [x] Reset click handler returns immediately while busy.
- [x] `updateComposerState()` disables reset while busy.
- [x] Reset still clears conversation, mission, replay ids, active run id, and artifact cache when idle.
- [x] Focused web tests pass.
- [x] Full unit tests pass.
- [x] Trellis task validation passes.
- [x] Changes are committed locally.

## Technical Notes

- Do not add another modal or operations panel.
- Do not abort the active stream through reset; users should use Stop for that path.
