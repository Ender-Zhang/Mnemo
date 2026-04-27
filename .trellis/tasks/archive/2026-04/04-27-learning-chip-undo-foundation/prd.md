# Learning Chip Undo Foundation

## Goal
Let users revoke a memory learning chip from the same single-chat surface after a candidate has been accepted into durable memory.

## Requirements
- Add a compact `undo` action to the existing `/api/learning/memory` endpoint.
- Undo must use existing memory curation primitives rather than introducing a new workflow.
- If an accepted candidate created a stable memory page, undo must move that page out of active recall and record durable tombstones.
- The web client must expose a small inline undo action for resolved memory learning chips.
- Keep errors JSON-normalized and keep browser state local to the card.

## Acceptance Criteria
- [x] `POST /api/learning/memory` accepts `{ "action": "undo" }`.
- [x] Undo of an accepted memory candidate tombstones the linked stable page and the candidate.
- [x] Undo returns a compact payload with updated candidate status and affected page id when present.
- [x] The no-build frontend shows an inline undo option after a successful learning action.
- [x] Tests cover API success/error behavior and frontend asset hooks.

## Technical Notes
- Use `MemoryEngine` as the domain boundary.
- Reuse `memory_links` relation `promoted_to` to find the promoted page.
- Do not add a dashboard, browser persistence key, or fixed background workflow.
