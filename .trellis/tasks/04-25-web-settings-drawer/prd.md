# Web Settings Drawer

## Goal
Add a lightweight user-facing settings drawer to the single-chat web UI without turning Mnemo into an operations dashboard.

## Requirements
- Keep the main screen as one persistent chat surface and one composer.
- Add a low-frequency settings entry in the top bar.
- Expose compact settings data through the stdlib web API.
- Store only user-editable quiet-hours settings in a lightweight state-dir JSON file.
- Summarize connected runtime/workspace state, permission behavior, learned preferences, and data-control actions from existing state.
- Avoid database migrations, new frontend build tooling, secrets exposure, or raw memory/artifact bodies in settings payloads.

## Acceptance Criteria
- [x] `GET /api/settings` returns compact connected app, permission, quiet-hours, learned preference, and data-control sections.
- [x] `POST /api/settings` updates quiet-hours settings and rejects invalid payloads with JSON errors.
- [x] Web assets render a settings drawer from the single chat shell.
- [x] Settings drawer can save quiet hours and prefill chat for preference/data-control actions.
- [x] Frontend/backend specs and implementation checklist reflect the feature.
- [x] Web tests cover API behavior and asset hooks.

## Technical Notes
- This task should not implement standing authority or app OAuth.
- Learned preferences should be summaries only; full memory pages stay behind existing memory APIs/tools.
- Settings are product controls, not operational logs.
