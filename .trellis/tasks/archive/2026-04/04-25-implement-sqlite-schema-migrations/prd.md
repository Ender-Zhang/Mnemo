# Implement SQLite Schema Migrations

## Goal
Replace ad-hoc SQLite schema upgrades with a small explicit migration system so future Mnemo state changes can evolve existing user state safely.

## Requirements
- Add a migration ledger table that records applied migration versions and names.
- Keep `schema_meta.schema_version` authoritative and aligned with the latest migration version.
- Make `StateStore.initialize()` idempotent for new and existing state directories.
- Preserve compatibility with current databases that only have `schema_meta` and `_ensure_column` style upgrades.
- Add tests for fresh initialization, idempotency, and upgrading a legacy database.
- Update backend database spec, checklist, and Trellis task state.

## Acceptance Criteria
- [x] Fresh initialization creates all current tables and records all migrations.
- [x] Calling `initialize()` repeatedly does not duplicate migrations or fail.
- [x] A legacy schema with missing post-v1 columns is upgraded.
- [x] `schema_meta.schema_version` equals the latest schema version after initialization.
- [x] Full tests pass.
- [x] Git is committed and pushed.

## Technical Notes
- Keep this lightweight: local SQLite only, no external migration framework.
- Migration functions should be deterministic and transaction-safe.
- Existing storage APIs must keep their current behavior.
