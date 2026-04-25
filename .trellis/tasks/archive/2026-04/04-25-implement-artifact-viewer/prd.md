# Implement Artifact Viewer

## Goal

Make artifact cards in the single-chat web UI usable: users should be able to open an artifact produced during a run and read its stored content without exposing artifact bodies in every streamed event.

## Scope

- Add a lightweight read API for stored artifacts.
- Add storage access for one artifact by id.
- Keep streamed `artifact.card` compact, with metadata only.
- Render artifact cards as interactive UI elements in `app.js`.
- Fetch and display the artifact body on demand.
- Preserve chat resume/de-duplication behavior.
- Cover API and frontend asset behavior with tests.
- Update checklist and code specs.

## Acceptance

- [x] Web API returns a stored artifact by id with id, mission id, run id, kind, title, body, and timestamps.
- [x] Missing `artifact_id` returns HTTP 400.
- [x] Unknown `artifact_id` returns HTTP 404.
- [x] `artifact.card` events carry useful artifact metadata without full body content.
- [x] Web asset renders artifact cards with on-demand body loading.
- [x] Existing event replay/resume behavior still passes.
- [x] Full unit suite passes.
- [x] Changes are committed locally.
