# Normalize Missing Run Trace CLI Errors

## Goal
Make trace inspection commands fail clearly when the requested run id does not exist, instead of returning empty event/replay output.

## Requirements
- `mnemo events <run_id>` must validate run existence before loading ledger events.
- `mnemo replay <run_id>` must validate run existence before summarizing a trace.
- `mnemo harness replay <run_id>` must validate run existence before summarizing a trace.
- Missing run ids must exit non-zero through `MnemoError` as `mnemo: run not found: <id>`.
- Existing successful event/replay behavior must remain unchanged.

## Acceptance Criteria
- [x] Existing `events` and `replay` commands still work for real runs.
- [x] Missing run ids in `events` are normalized without tracebacks.
- [x] Missing run ids in `replay` are normalized without tracebacks.
- [x] Missing run ids in `harness replay` are normalized without tracebacks.
- [x] Error-handling specs and tests are updated.

## Validation
- `python3.13 -m unittest tests.test_cli.CliTests.test_events_chat_and_replay_commands`
- `python3.13 -m unittest tests.test_cli.CliTests.test_harness_eval_and_replay_commands`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`
- `python3 ./.trellis/scripts/task.py validate 04-25-normalize-missing-run-trace-cli-errors`
- `git diff --check`
- Temporary venv wheel build/install smoke with `tests/package_install_smoke.py`

## Technical Notes
- No storage schema changes are required.
- Validate through `StateStore.get_run()` at CLI boundaries.
