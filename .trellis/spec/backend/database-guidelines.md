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
- `StateStore.get_conversation(conversation_id: str) -> dict[str, Any] | None`
- `StateStore.list_conversations(*, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.get_mission(mission_id: str) -> dict[str, Any] | None`
- `StateStore.list_missions(*, conversation_id: str | None = None, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.get_run(run_id: str) -> dict[str, Any] | None`
- `StateStore.list_runs(*, status: str | None = None, conversation_id: str | None = None, mission_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.cancel_run(run_id: str, *, reason: str = "cancelled") -> dict[str, Any]`
- `StateStore.is_run_cancelled(run_id: str) -> bool`
- `StateStore.record_session_message(conversation_id: str, mission_id: str, run_id: str, role: str, content: str, *, metadata: dict[str, Any] | None = None) -> str`
- `StateStore.search_session_messages(query: str, limit: int = 5) -> list[dict[str, Any]]`
- `StateStore.enqueue_run_request(message: str, *, conversation_id: str | None = None, mission_id: str | None = None, metadata: dict[str, Any] | None = None, available_at: float | None = None) -> str`
- `StateStore.list_queue_items(status: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.claim_next_queue_item(worker_id: str) -> dict[str, Any] | None`
- `StateStore.heartbeat_queue_item(queue_id: str) -> None`
- `StateStore.complete_queue_item(queue_id: str, status: str, *, run_id: str | None = None, error: str | None = None) -> None`
- `StateStore.cancel_queue_item(queue_id: str, *, reason: str = "cancelled") -> dict[str, Any]`
- `StateStore.recover_stale_queue_items(stale_after_s: float = 900.0) -> list[dict[str, Any]]`
- `StateStore.queue_stats() -> dict[str, Any]`
- `StateStore.upsert_generated_tool(*, candidate_id: str, name: str, description: str, risk: str, input_schema: dict[str, Any], implementation: dict[str, Any], status: str = "active") -> str`
- `StateStore.get_generated_tool(name: str) -> dict[str, Any] | None`
- `StateStore.list_generated_tools(status: str | None = "active", limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.update_generated_tool_status(name: str, status: str) -> None`
- `StateStore.add_eval_case(run_id: str, name: str, case: dict[str, Any]) -> str`
- `StateStore.get_eval_case(case_id: str) -> dict[str, Any] | None`
- `StateStore.list_eval_cases(status: str | None = None, *, tool_name: str | None = None, skill_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.update_eval_case_status(case_id: str, status: str, *, result: dict[str, Any] | None = None) -> None`
- `StateStore.upsert_artifact(mission_id: str, run_id: str, title: str, body: str, kind: str = "markdown") -> str`
- `StateStore.get_artifact(artifact_id: str) -> dict[str, Any] | None`
- `StateStore.list_artifacts(*, mission_id: str | None = None, run_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.add_inbox_item(*, category: str, title: str, priority: int = 2, body: str | None = None, action_type: str = "none", action_data: dict[str, Any] | None = None, source_run_id: str | None = None, expires_at: float | None = None) -> str`
- `StateStore.get_inbox_item(item_id: str) -> dict[str, Any] | None`
- `StateStore.list_inbox_items(*, status: str | None = "open", category: str | None = None, priority_lte: int | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.resolve_inbox_item(item_id: str, resolution: str, *, notes: str | None = None) -> dict[str, Any]`
- `StateStore.list_working_notes(status: str | None = "open", limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.list_memory_links(source_id: str) -> list[dict[str, Any]]`
- `StateStore.list_memory_backlinks(target_id: str) -> list[dict[str, Any]]`
- `SchemaMigration(version: int, name: str, apply: Callable[[sqlite3.Connection], None])`
- Internal: `_apply_schema_migrations(conn: sqlite3.Connection) -> None`
- Internal: `_ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None`
- `RunLedger.chat_events_after_event_id(run_id: str, event_id: str | None) -> list[dict[str, Any]]`

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
- `list_conversations()` returns compact conversation metadata ordered by recency.
- `list_missions()` returns compact mission metadata ordered by recency, supports conversation/status filters, and omits checkpoint data.
- `get_mission()` returns full mission data with parsed `checkpoint`.
- CLI continuity inspection must use read APIs and remain read-only: `mnemo conversations list/show` and `mnemo missions list/show`.
- Runs may be `running`, `completed`, `failed`, or `cancelled`.
- `list_runs()` returns compact run metadata ordered by recency, supports status/conversation/mission filters, and includes `input_preview` instead of full input/output bodies.
- CLI run inspection must use read APIs and remain read-only: `mnemo runs list` and `mnemo runs show <run_id>`.
- `cancel_run()` marks only non-terminal runs as `cancelled`; terminal runs return unchanged.
- Runtime code should check `is_run_cancelled()` between provider/tool steps and complete with `status="cancelled"`.
- Web and CLI cancellation entry points append `run.cancel.requested` with reason, changed flag, and observed status.
- `session_messages` stores L4 raw run messages tied to conversation, mission, and run ids.
- `create_run()` records the user input as a `role="user"` session message in the same transaction as the run row.
- `complete_run()` records a non-empty assistant output once as a `role="assistant"` session message.
- The v6 session message migration backfills existing `runs.input_text` and non-empty `runs.output_text` into `session_messages` before rebuilding the FTS index.
- `search_session_messages()` returns compact snippet results only: `id`, `message_id`, `conversation_id`, `mission_id`, `run_id`, `role`, `snippet`, and `created_at`.
- Session search must not return full `content` unless a future explicit read API is added.
- L4 search uses SQLite FTS5 when available and falls back to bounded `LIKE` snippets when FTS5 is unavailable.
- `run_queue` stores durable local work with `message`, optional conversation/mission ids, structured metadata, status, attempts, worker id, produced run id, timing fields, and last error.
- Queue statuses are `pending`, `running`, `completed`, `failed`, and `cancelled`.
- Claiming a queue item moves one due pending row to `running`, increments `attempts`, and records worker/heartbeat timestamps.
- Completing a queue item accepts only `completed` or `failed`; completed rows store the produced `run_id`, failed rows store `last_error`.
- Cancelling a pending queue item marks it `cancelled` so it cannot be claimed.
- Cancelling a non-pending queue item returns unchanged; active work should be cancelled through its `run_id`.
- Stale recovery moves old `running` rows back to `pending` and clears worker/claim/heartbeat fields.
- Daemon code must execute queued work through the existing `RunRequest` runtime path.
- `generated_tools` stores installed generated tool manifests with candidate provenance, provider-facing schema, implementation descriptor, and active/disabled status.
- Generated tool implementations are data, not executable code.
- `eval_cases` stores draft/passed/failed cases with source run provenance and structured `case` / `result` JSON payloads.
- `artifacts` stores full artifact bodies with mission/run provenance; streamed UI events should reference artifact ids instead of carrying body text.
- `get_artifact()` returns `None` for unknown ids and a plain JSON-serializable dict for known ids.
- `list_artifacts()` returns artifact metadata ordered by recency, supports mission/run filters, and omits body text.
- `inbox_items` stores asynchronous user-visible items with priority, category, title/body, action type, structured `action_data`, optional source run, status, resolution, and timestamps.
- Inbox statuses are `open` and `resolved`; resolutions are `accepted`, `rejected`, and `ignored`.
- `add_inbox_item()` validates category/title and priority 0..3.
- `list_inbox_items()` returns parsed `action_data`, supports status/category/priority filters, and orders by priority then creation time.
- `resolve_inbox_item()` resolves only open items; repeated resolution returns `changed=false` with the existing item.
- CLI/Web Inbox inspection must use storage APIs and not read raw SQLite rows directly.
- `working_notes` stores W0 notes with mission/run provenance, metadata, processing status, and result payloads.
- CLI W0 inspection must use the read API and remain read-only: `mnemo memory notes`.
- `memory_links` can be read by source or target id; both directions return the same link shape ordered by weight and recency.
- CLI graph inspection must use these read APIs and remain read-only: `mnemo memory links <memory_id>`.
- Chat replay by `event_id` is derived from persisted `chat.event` payloads in run order.
- Unknown chat `event_id` returns all chat events for the run so clients can safely rehydrate.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Fresh state dir | Create schema, directories, migration rows, and latest `schema_version` | `tests/test_storage.py` |
| Repeated initialize | No duplicate migration rows and no failure | `tests/test_storage.py` |
| Legacy v1 DB missing generated lifecycle columns | Add missing columns and preserve existing rows | `tests/test_storage.py` |
| Pre-initialized version read | Return `0` or empty migration list instead of crashing | Storage API behavior |
| Continuity listing | List conversations/missions without mission checkpoint bodies | `tests/test_storage.py`, `tests/test_cli.py` |
| Run event append | Persist run event and matching pending outbox row in one call | `tests/test_storage.py` |
| Run listing | List/filter compact run metadata without full bodies | `tests/test_storage.py`, `tests/test_cli.py` |
| Run cancellation | Running run becomes `cancelled`; terminal repeat is unchanged | `tests/test_storage.py`, `tests/test_cli.py` |
| Web run cancellation | `POST /api/runs/cancel` marks run cancelled and records `run.cancel.requested` | `tests/test_web.py` |
| L4 session message persistence | Run user and assistant messages are queryable as snippets with conversation/mission/run ids | `tests/test_storage.py` |
| L4 migration backfill | Existing v5 run input/output rows become searchable session snippets after initialize | `tests/test_storage.py` |
| Future outbox availability | Exclude future pending rows from due pending list | `tests/test_storage.py` |
| Failed outbox mark | Increment attempts and store error | `tests/test_storage.py` |
| Invalid outbox status | Raise `ValueError` | `tests/test_storage.py` |
| Backup round trip | Export and import state with queryable memory, run events, outbox, and managed files | `tests/test_storage.py`, `tests/test_cli.py` |
| Non-empty import target | Reject unless `replace=True` | `tests/test_storage.py` |
| Unsafe archive path | Reject path traversal or unsupported archive members before extraction | `tests/test_storage.py` |
| Queue lifecycle | Enqueue, claim, heartbeat, complete, and stats preserve expected state | `tests/test_storage.py` |
| Queue cancellation | Pending queue item becomes `cancelled` and cannot be claimed; running items remain unchanged | `tests/test_storage.py`, `tests/test_daemon.py`, `tests/test_cli.py` |
| Queue crash recovery | Stale running jobs return to pending | `tests/test_storage.py`, `tests/test_daemon.py` |
| Daemon CLI | Enqueue, run, status, and recover operate through persisted queue | `tests/test_cli.py` |
| Generated tool storage | Round-trip active/disabled generated tool manifests | `tests/test_storage.py` |
| Eval case storage | Add, list by target/status, and update result payloads | `tests/test_storage.py`, `tests/test_cli.py` |
| Artifact lookup | Round-trip artifact metadata/body by id, unknown id returns `None` | `tests/test_storage.py` |
| Artifact listing | List/filter artifact metadata without body text | `tests/test_storage.py`, `tests/test_cli.py` |
| Inbox storage | Add, list/filter, read, and resolve Inbox items with parsed action data | `tests/test_storage.py`, `tests/test_cli.py`, `tests/test_web.py` |
| Inbox repeated resolve | Resolved item returns unchanged instead of mutating resolution again | `tests/test_storage.py` |
| CLI working notes | Open and processed W0 notes are exposed without storage mutation | `tests/test_cli.py` |
| Memory backlinks | Reverse link lookup supports associative memory recall | `tests/test_memory.py` |
| CLI memory links | Link/backlink lookup is exposed without storage mutation | `tests/test_cli.py` |
| Chat replay after event id | Returns only later chat events, or full replay if unknown | `tests/test_web.py` |

### 5. Good/Base/Bad Cases
- Good: add a new schema change by appending one `SchemaMigration` and bumping `SCHEMA_VERSION`.
- Good: make migrations idempotent with `CREATE ... IF NOT EXISTS` or `_ensure_column`.
- Good: consume pending outbox events through `list_outbox_events()` and mark delivery through `mark_outbox_event()`.
- Good: keep backup archives limited to managed state paths and validate every member before extraction.
- Good: drain queued work through the same runtime entry points used by CLI/web runs.
- Good: check run cancellation between interruptible runtime steps.
- Good: install generated tools by persisting a manifest row and loading it through `ToolRegistry.from_store()`.
- Good: expose artifact bodies through explicit artifact lookup APIs instead of duplicating bodies in chat events.
- Good: store user decisions as Inbox items and return item ids in chat events.
- Good: expose browser replay by `ChatEvent.event_id`, not internal run-event sequence.
- Good: expose L4 session recall as bounded snippets with provenance ids, not full transcripts.
- Base: current full schema may create all tables before migrations reconcile legacy gaps.
- Bad: mutate the schema in feature code outside `StateStore.initialize()`.
- Bad: overwrite `schema_meta.schema_version` without recording the migration ledger.
- Bad: poll `run_events` directly from daemon code when outbox delivery state is needed.
- Bad: extract zip members directly with `extractall()`.
- Bad: create a second daemon worker for the same state directory without acquiring the local lock.
- Bad: treating cancellation as provider failure after the cancellation signal has been observed.

### 6. Tests Required
- Fresh initialization records all migrations.
- Initialization is idempotent.
- Legacy schemas are upgraded in place.
- Outbox table exists on fresh and upgraded state dirs.
- Conversation and mission continuity list/show behavior is covered.
- Appending a run event creates a matching outbox event.
- Run list/show CLI and compact storage summaries are covered.
- L4 session message storage, migration backfill, and search snippets are covered.
- Outbox list and mark lifecycle is covered.
- Backup export/import round-trip is covered.
- Import target and archive safety failures are covered.
- Queue lifecycle, daemon drain, single-instance lock, and stale recovery are covered.
- Run and queue cancellation are covered at storage, CLI, daemon, and provider runtime boundaries.
- Generated tool manifest round-trip and migration coverage are covered.
- Eval case add/list/update behavior is covered.
- Artifact storage round-trip by id is covered.
- Artifact metadata list/filter behavior is covered without duplicating body text.
- Inbox storage round-trip, filters, and resolution lifecycle are covered.
- Web event replay by `sinceEventId` is covered.
- Existing storage round-trips still pass after migration changes.
