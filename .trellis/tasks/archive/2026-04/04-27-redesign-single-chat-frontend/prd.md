# Redesign Single Chat Frontend

## Goal
Turn the existing Mnemo web UI into a polished user-facing single-chat interface that matches the system's capabilities: one universal composer, streaming model output, inline actions, decisions, learning, artifacts, recall, settings, and compact runtime visibility.

## Requirements
- Preserve the no-build stdlib frontend: only `index.html`, `app.css`, and `app.js`.
- Keep the user's primary interaction model as one chat box, not an operations dashboard.
- Redesign the shell around a slim rail, chat canvas, contextual activity side panel, and universal composer.
- Make streaming output, action progress, memory learning chips, decision cards, artifact previews, recall cards, and settings feel like one coherent product.
- Keep all dynamic text safe via `textContent`; no model/user HTML injection.
- Preserve replay/resume, cancellation, learning actions, Inbox resolution, artifact fetch/actions, settings drawer, and composer prefill behavior.
- Add asset-level tests for the new shell and interaction language.

## Acceptance Criteria
- [x] Web UI presents a polished single-chat shell with rail, top bar, chat timeline, contextual activity panel, and universal composer.
- [x] Composer exposes attachment, voice, app mention, send, and stop affordances without adding new unsupported backend routes.
- [x] Inline event cards remain functional for actions, learning, decisions, recall, artifacts, settings, and errors.
- [x] Activity panel mirrors compact run/action/memory/decision/artifact status without becoming the primary workflow.
- [x] Mobile layout keeps one chat box and collapses secondary surfaces cleanly.
- [x] Static asset tests and full web/unit/package gates pass.

## Technical Notes
- The generated visual direction is stored outside the repo by the image tool and is used only as design guidance.
- This task does not add a bundler, frontend framework, or new backend workflow.
