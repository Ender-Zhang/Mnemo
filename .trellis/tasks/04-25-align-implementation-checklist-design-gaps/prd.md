# Align Implementation Checklist With Design Gaps

## Goal
Make the implementation checklist accurately reflect the current codebase against the design package, separating runnable core slices from incomplete full-design capabilities and optional extensions.

## Requirements
- Reclassify checklist items that are currently over-marked as complete when only a foundation slice exists.
- Preserve important design scope; do not delete memory, skills, tools, prompt, frontend, runtime, or harness details.
- Add a concise gap backlog that maps directly to the design package.
- Keep the language useful for future Trellis tasks and implementation planning.
- Avoid changing runtime behavior in this task.

## Acceptance Criteria
- [x] `IMPLEMENTATION_CHECKLIST.md` distinguishes `[x]`, `[~]`, and `[ ]` honestly.
- [x] Core runnable capabilities remain marked complete where tests and smoke paths exist.
- [x] Known missing areas include memory depth, SDK/MCP, Soul/bootstrap, learning packet, Decision/Inbox, frontend interaction gaps, RuntimeAdapter, Watch/Sense, and stronger harness gates.
- [x] The checklist no longer claims "no known checklist gaps".
- [x] Validation confirms this is a docs-only alignment with no accidental code changes.

## Validation
- `git diff --check`
- `python3 ./.trellis/scripts/task.py validate 04-25-align-implementation-checklist-design-gaps`
- Manual review against `design/README.md`, `design/01-memory-engine.md`, `design/05-interfaces-data-security.md`, `design/07-runtime-harness.md`, `design/08-frontend-chat.md`, and `design/09-roadmap-principles.md`

## Technical Notes
- This task should not edit production code.
- If a checklist item is partially implemented, prefer `[~]` with a short explanation over deleting the item.
