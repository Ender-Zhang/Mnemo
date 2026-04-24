# Implement Backup Export Import

## Problem
Mnemo has persistent SQLite state, generated skills, memory wiki pages, run ledgers, and artifacts, but no supported way to export or restore that local state. Users need a lightweight recovery path before daemon and long-running queue work makes state more valuable.

## Scope
- Add a local zip-based state export API.
- Add a validated import API with replace protection.
- Add CLI commands for export and import.
- Cover round-trip, non-empty target, and unsafe archive cases.
- Update implementation checklist and storage contracts.

## Out of Scope
- Remote/cloud backup.
- Incremental backup scheduling.
- Encryption or privacy controls.
- Multi-machine conflict merge.

## Acceptance
- [x] `StateStore` can export the managed state files into a zip archive with a manifest.
- [x] `StateStore` can import a valid archive into an empty state directory.
- [x] Import can replace existing managed state only when explicitly requested.
- [x] Import rejects unsafe archive paths.
- [x] CLI supports `mnemo backup export` and `mnemo backup import`.
- [x] Restored state is migrated to the current schema and remains queryable.
- [x] Tests cover storage and CLI behavior.
- [x] Implementation checklist and backend storage specs are updated.
- [x] Changes are committed and pushed.
