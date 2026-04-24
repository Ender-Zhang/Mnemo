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
- `StateStore.enqueue_outbox_event(topic: str, payload: dict[str, Any], *, aggregate_id: str | None = None, available_at: float | None = None) -> str`
- `StateStore.list_outbox_events(status: str | None = "pending", *, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.mark_outbox_event(event_id: str, status: str, *, error: str | None = None) -> None`
- `StateStore.export_state(archive_path: str | Path) -> dict[str, Any]`
- `StateStore.import_state(archive_path: str | Path, *, replace: bool = False) -> dict[str, Any]`
- `StateStore.enqueue_run_request(message: str, *, conversation_id: str | None = None, mission_id: str | None = None, metadata: dict[str, Any] | None = None, available_at: float | None = None) -> str`
- `StateStore.list_queue_items(status: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.claim_next_queue_item(worker_id: str) -> dict[str, Any] | None`
- `StateStore.heartbeat_queue_item(queue_id: str) -> None`
- `StateStore.complete_queue_item(queue_id: str, status: str, *, run_id: str | None = None, error: str | None = None) -> None`
- `StateStore.recover_stale_queue_items(stale_after_s: float = 900.0) -> list[dict[str, Any]]`
- `StateStore.queue_stats() -> dict[str, Any]`
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
- `event_outbox` stores durable delivery records with `topic`, `aggregate_id`, structured `payload_json`, `status`, `attempts`, `available_at`, and `last_error`.
- `StateStore.append_event()` mirrors each `run_events` row into `event_outbox` in the same SQLite transaction.
- Mirrored run-event outbox payloads include `run_id`, `seq`, `event_type`, original `payload`, and `created_at`.
- `list_outbox_events(status="pending")` returns only pending rows whose `available_at` is due, ordered by `available_at`, `created_at`, then `id`.
- `mark_outbox_event(..., status="failed")` increments `attempts` and records `last_error`.
- `mark_outbox_event(..., status="sent")` clears `last_error` and leaves `attempts` unchanged.
- `export_state()` writes a zip archive with a `manifest.json`, current `state.db`, and managed state directories: `wiki`, `skills`, `runs`, and `artifacts`.
- `import_state()` validates the manifest, rejects archives from newer schema versions, rejects unsafe paths, and migrates the restored database through `initialize()`.
- Import into non-empty managed state requires `replace=True`.
- Replace mode removes only managed Mnemo paths, not unrelated files in the state directory.
- `run_queue` stores durable local work with `message`, optional conversation/mission ids, structured metadata, status, attempts, worker id, produced run id, timing fields, and last error.
- Queue statuses are `pending`, `running`, `completed`, and `failed`.
- Claiming a queue item moves one due pending row to `running`, increments `attempts`, and records worker/heartbeat timestamps.
- Completing a queue item accepts only `completed` or `failed`; completed rows store the produced `run_id`, failed rows store `last_error`.
- Stale recovery moves old `running` rows back to `pending` and clears worker/claim/heartbeat fields.
- Daemon code must execute queued work through the existing `RunRequest` runtime path.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Fresh state dir | Create schema, directories, migration rows, and latest `schema_version` | `tests/test_storage.py` |
| Repeated initialize | No duplicate migration rows and no failure | `tests/test_storage.py` |
| Legacy v1 DB missing generated lifecycle columns | Add missing columns and preserve existing rows | `tests/test_storage.py` |
| Pre-initialized version read | Return `0` or empty migration list instead of crashing | Storage API behavior |
| Run event append | Persist run event and matching pending outbox row in one call | `tests/test_storage.py` |
| Future outbox availability | Exclude future pending rows from due pending list | `tests/test_storage.py` |
| Failed outbox mark | Increment attempts and store error | `tests/test_storage.py` |
| Invalid outbox status | Raise `ValueError` | `tests/test_storage.py` |
| Backup round trip | Export and import state with queryable memory, run events, outbox, and managed files | `tests/test_storage.py`, `tests/test_cli.py` |
| Non-empty import target | Reject unless `replace=True` | `tests/test_storage.py` |
| Unsafe archive path | Reject path traversal or unsupported archive members before extraction | `tests/test_storage.py` |
| Queue lifecycle | Enqueue, claim, heartbeat, complete, and stats preserve expected state | `tests/test_storage.py` |
| Queue crash recovery | Stale running jobs return to pending | `tests/test_storage.py`, `tests/test_daemon.py` |
| Daemon CLI | Enqueue, run, status, and recover operate through persisted queue | `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: add a new schema change by appending one `SchemaMigration` and bumping `SCHEMA_VERSION`.
- Good: make migrations idempotent with `CREATE ... IF NOT EXISTS` or `_ensure_column`.
- Good: consume pending outbox events through `list_outbox_events()` and mark delivery through `mark_outbox_event()`.
- Good: keep backup archives limited to managed state paths and validate every member before extraction.
- Good: drain queued work through the same runtime entry points used by CLI/web runs.
- Base: current full schema may create all tables before migrations reconcile legacy gaps.
- Bad: mutate the schema in feature code outside `StateStore.initialize()`.
- Bad: overwrite `schema_meta.schema_version` without recording the migration ledger.
- Bad: poll `run_events` directly from daemon code when outbox delivery state is needed.
- Bad: extract zip members directly with `extractall()`.
- Bad: create a second daemon worker for the same state directory without acquiring the local lock.

### 6. Tests Required
- Fresh initialization records all migrations.
- Initialization is idempotent.
- Legacy schemas are upgraded in place.
- Outbox table exists on fresh and upgraded state dirs.
- Appending a run event creates a matching outbox event.
- Outbox list and mark lifecycle is covered.
- Backup export/import round-trip is covered.
- Import target and archive safety failures are covered.
- Queue lifecycle, daemon drain, single-instance lock, and stale recovery are covered.
- Existing storage round-trips still pass after migration changes.
