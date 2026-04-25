# Expose Memory Notes CLI

## Goal
Expose W0 working notes through the CLI so humans and harnesses can inspect the model-written observations that DreamCycle may later convert into memory candidates.

## Requirements
- Add `mnemo memory notes [--status STATUS|all] [--limit N] [--state-dir DIR] [--json]`.
- Default to open notes, matching `StateStore.list_working_notes()` and DreamCycle input.
- Support `--status all` for processed/skipped note inspection.
- Keep the command read-only; note creation remains model/tool-driven and DreamCycle owns processing.
- JSON output returns notes with metadata/result payloads.
- Non-JSON output prints compact rows with id, status, retention, mission/run ids, and short content.
- Update README, backend memory/database contracts, implementation checklist, and CLI regression tests.

## Acceptance Criteria
- [x] `mnemo memory notes --json` returns open notes by default.
- [x] `mnemo memory notes --status all --json` includes processed notes.
- [x] Non-JSON output prints compact rows with retention and content.
- [x] The command does not mutate note status or result payloads.
- [x] Source unit tests and Trellis task validation pass.

## Validation Notes
- `python3.13 -m unittest tests.test_cli.CliTests.test_memory_notes_command_lists_open_and_processed_w0_notes`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`
- `task.py validate 04-25-expose-memory-notes-cli`
- Temporary venv `pip wheel` install smoke with `tests/package_install_smoke.py`

## Technical Notes
- Reuse `StateStore.list_working_notes()`.
- Treat `--status all` as `None` for storage calls.
- Do not add a new memory workflow or storage schema.
