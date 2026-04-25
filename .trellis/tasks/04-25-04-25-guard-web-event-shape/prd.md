# Guard Web Event Shape

## Goal
Make the single-chat web client tolerate non-object stream or replay event payloads without crashing the timeline renderer.

## Requirements
- Add a shape guard at the browser event boundary before persistence, de-duplication, or rendering.
- Keep unknown object event types ignored by the existing default route.
- Preserve all existing event rendering behavior for valid events.
- Add an asset-level regression assertion in `tests/test_web.py`.
- Update frontend type-safety spec and implementation checklist.

## Acceptance Criteria
- [x] `handleEvent` returns early for `null`, arrays, or other non-object payloads.
- [x] Web asset test asserts the event shape guard exists.
- [x] Type-safety spec points missing optional event data coverage to `tests/test_web.py`.
- [x] Targeted and full test suites pass.

## Technical Notes
- This is a frontend boundary hardening task.
- Do not add a build step or a new frontend framework.
