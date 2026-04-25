# Web Artifact Actions

## Goal
Expand web artifact cards beyond open/view while keeping artifact work inside the single chat composer.

## Requirements
- Keep the primary experience as one chat timeline and one composer.
- Add compact artifact actions for continue editing, export, compare, send, and diff-oriented apply/revert prompts.
- Fetch full artifact bodies only on explicit user action.
- Extend the artifact API with compact related artifact metadata for comparison without returning related bodies.
- Avoid new build tooling, database migrations, or a separate artifact dashboard.

## Acceptance Criteria
- [x] `/api/artifacts?artifact_id=...` returns the requested artifact plus compact related artifacts from the same mission.
- [x] Artifact cards render continue/export/compare/send actions.
- [x] Diff or patch artifact cards render apply/revert prompt actions.
- [x] Export downloads the fetched artifact body from the browser without changing backend state.
- [x] Compare shows compact related artifact options and reuses the composer for comparison/revert intent.
- [x] Web specs, checklist, and tests are updated.

## Technical Notes
- Applying patches or sending messages remains model/tool-led through the normal composer and permission flow.
- This task should not add a full version-control system for artifacts.
