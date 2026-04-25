# Implement Learning Chip Actions

## Goal

Let users act on inline memory learning chips in the single chat surface so a draft memory candidate can be accepted for future use, marked as this-turn-only, or rejected without leaving the conversation.

## Requirements

- Keep learning actions inline in the existing chat timeline.
- Add a small web API that resolves memory learning candidates by id.
- Reuse the existing `MemoryEngine.promote_candidate()` and `reject_candidate()` paths.
- Persist a compact run event when a source run is available.
- Keep streamed `learning.chip` events compact and free of raw memory bodies.
- Keep the system lightweight: no dashboard, no workflow router, no schema migration unless necessary.

## Acceptance Criteria

- [x] `/api/learning/memory` accepts `candidate_id` and `action`.
- [x] `accept` promotes the candidate into an active memory page and marks it promoted.
- [x] `this_time` leaves no stable memory and marks the candidate as rejected for ephemeral use.
- [x] `reject` leaves no stable memory and marks the candidate rejected.
- [x] Missing or invalid inputs return JSON 400/404 errors.
- [x] Frontend learning chips render compact actions and disable buttons while resolving.
- [x] Tests cover the API path, asset hooks, and existing replay/stream contracts.

## Technical Notes

- This is a cross-layer feature: Runtime projection → Web API → MemoryEngine → StateStore → frontend card.
- The action names are provider/frontend API contract; labels can remain UI text.
- Future undo/high-risk confirmation can build on the same endpoint without adding a separate learning dashboard.
