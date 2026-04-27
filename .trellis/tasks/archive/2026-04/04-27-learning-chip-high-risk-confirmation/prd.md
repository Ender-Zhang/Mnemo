# Learning Chip High-Risk Confirmation

## Goal
Make high-risk memory learning candidates visibly require user confirmation in the existing inline learning chip, using the safety/status signals already produced by `memory_write_candidate`.

## Requirements
- Project `needs_review:*` and safety `requires_review=true` memory candidates into learning chip metadata.
- Keep the action surface inside the same `/api/learning/memory` accept/this_time/reject/undo API.
- Use clearer user-facing wording for risky memory learning, such as `确认记住`, without adding a new workflow, dashboard, or browser persistence key.
- Preserve low-risk learning chip behavior.
- Keep prompt-injection safety evidence compact and avoid exposing raw evidence text in chat events.

## Acceptance Criteria
- [x] Runtime learning chip payloads include compact confirmation metadata for review-gated memory candidates.
- [x] Frontend learning chips show confirmation wording for review-gated memory candidates.
- [x] Low-risk memory learning chips keep the existing `以后这样` action.
- [x] Tests cover runtime projection and no-build frontend asset hooks.

## Technical Notes
- Source of truth is `ToolResult.result.status` plus optional `ToolResult.result.safety`.
- The model still decides when to create candidates; this only reflects existing safety signals in the UI.
- No storage schema changes.
