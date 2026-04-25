# Expose Runs Inspection CLI

## Goal
Expose durable run history through a compact read-only CLI so users can find prior task runs before opening events, replay, prompts, or artifacts.

## Requirements
- Add `mnemo runs list` with optional `--status`, `--conversation-id`, `--mission-id`, `--limit`, and `--json`.
- Add `mnemo runs show <run_id>` with optional `--json`.
- Keep list output compact with input previews, not full run input/output bodies.
- Normalize unknown run ids through `MnemoError` so CLI output has no traceback.
- Reuse `StateStore` read APIs; do not query SQLite directly from the CLI.

## Acceptance Criteria
- [x] CLI can list recent run metadata from the local state directory.
- [x] CLI can filter run metadata by status, conversation id, and mission id.
- [x] CLI can show one full run record by id.
- [x] Missing run reads exit non-zero with `mnemo: run not found: <id>`.
- [x] Storage, CLI, and docs/spec contracts are updated.

## Validation
- `python3.13 -m unittest tests.test_storage.StateStoreTests.test_list_runs_returns_compact_filterable_summaries`
- `python3.13 -m unittest tests.test_cli.CliTests.test_runs_list_and_show_commands_inspect_run_history`
- `python3.13 -m unittest tests.test_cli.CliTests.test_runs_cancel_and_daemon_cancel_commands`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest tests.test_storage`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`
- `python3 ./.trellis/scripts/task.py validate 04-25-expose-runs-inspection-cli`
- `git diff --check`
- Temporary venv wheel build/install smoke with `tests/package_install_smoke.py`

## Technical Notes
- This is a read-only observability feature; no schema migration should be required.
- `runs list` should be compact enough to use in agent context without pulling full outputs.
