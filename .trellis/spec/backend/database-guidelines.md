# Database Guidelines

## Scenario: SQLite State Store And Migrations

### 1. Scope / Trigger
- Trigger: changes to `mnemo/storage/sqlite.py`, SQLite schema, persisted state shape, or storage initialization.
- Goal: keep local state durable while allowing schema evolution without deleting user data.

### 2. Signatures
- `SCHEMA_VERSION: int`
- `StateStore.initialize() -> None`
- `StateStore.schema_version() -> int`
- `StateStore.applied_migrations() -> list[dict[str, Any]]`
- `SchemaMigration(version: int, name: str, apply: Callable[[sqlite3.Connection], None])`
- Internal: `_apply_schema_migrations(conn: sqlite3.Connection) -> None`
- Internal: `_ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None`

### 3. Contracts
- `StateStore.initialize()` creates state directories and all current SQLite tables.
- `schema_meta.schema_version` stores the latest applied schema version as a string.
- `schema_migrations` records one row per applied migration with `version`, `name`, and `applied_at`.
- `SCHEMA_VERSION` must equal the latest migration version.
- Initialization must be idempotent for fresh and existing state directories.
- Legacy databases without `schema_migrations` must be upgraded through the same `initialize()` entry point.
- Additive compatibility migrations should use `_ensure_column` so they can run against fresh and legacy schemas.
- Existing storage APIs must not require callers to run migrations explicitly.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Fresh state dir | Create schema, directories, migration rows, and latest `schema_version` | `tests/test_storage.py` |
| Repeated initialize | No duplicate migration rows and no failure | `tests/test_storage.py` |
| Legacy v1 DB missing generated lifecycle columns | Add missing columns and preserve existing rows | `tests/test_storage.py` |
| Pre-initialized version read | Return `0` or empty migration list instead of crashing | Storage API behavior |

### 5. Good/Base/Bad Cases
- Good: add a new schema change by appending one `SchemaMigration` and bumping `SCHEMA_VERSION`.
- Good: make migrations idempotent with `CREATE ... IF NOT EXISTS` or `_ensure_column`.
- Base: current full schema may create all tables before migrations reconcile legacy gaps.
- Bad: mutate the schema in feature code outside `StateStore.initialize()`.
- Bad: overwrite `schema_meta.schema_version` without recording the migration ledger.

### 6. Tests Required
- Fresh initialization records all migrations.
- Initialization is idempotent.
- Legacy schemas are upgraded in place.
- Existing storage round-trips still pass after migration changes.
