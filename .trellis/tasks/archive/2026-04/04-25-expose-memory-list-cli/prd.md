# Expose Memory List CLI

## Goal
Expose existing memory candidate/page listing APIs through the CLI so humans and harnesses can inspect memory state without direct SQLite access.

## Requirements
- Add `mnemo memory list [--kind candidate|page|all] [--status STATUS|all] [--limit N] [--state-dir DIR] [--json]`.
- Default to `--kind candidate --status draft` because candidate curation is the common manual path after model/tool learning.
- Support `--kind page` with default active pages when status is omitted.
- Support `--kind all --status all` for full debug inventory.
- Keep the command read-only and compact.
- Update README, backend memory contract, implementation checklist, and CLI regression tests.

## Acceptance Criteria
- [x] `mnemo memory list --json` returns draft candidates only by default.
- [x] `mnemo memory list --kind page --json` returns active memory pages by default.
- [x] `mnemo memory list --kind all --status all --json` returns candidates and pages without filtering by status.
- [x] Non-JSON output prints compact candidate/page rows with ids, status, confidence, and short text.
- [x] Source unit tests and Trellis task validation pass.

## Validation Notes
- `python3.13 -m unittest tests.test_cli.CliTests.test_memory_list_command_filters_candidates_and_pages`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`
- `task.py validate 04-25-expose-memory-list-cli`
- Temporary venv `pip wheel` install smoke with `tests/package_install_smoke.py`

## Technical Notes
- Reuse `StateStore.list_memory_candidates()` and `StateStore.list_memory_pages()`.
- Treat `--status all` as `None` for storage calls.
- Do not introduce a new memory workflow or mutate memory state.
