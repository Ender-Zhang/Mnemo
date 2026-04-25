# Expose Continuity Inspection CLI

## Goal
Expose stored conversations and missions through compact read-only CLI commands so users can find continuity ids for later turns without opening SQLite directly.

## Requirements
- Add `mnemo conversations list` with optional `--limit` and `--json`.
- Add `mnemo conversations show <conversation_id>` with optional `--json`.
- Add `mnemo missions list` with optional `--conversation-id`, `--status`, `--limit`, and `--json`.
- Add `mnemo missions show <mission_id>` with optional `--json`.
- Keep list outputs compact; mission checkpoints should only be returned by explicit `missions show`.
- Normalize unknown conversation/mission ids through `MnemoError` so CLI output has no traceback.
- Reuse `StateStore` read APIs; do not query SQLite directly from the CLI.

## Acceptance Criteria
- [x] CLI can list conversation metadata.
- [x] CLI can show one conversation by id.
- [x] CLI can list mission metadata and filter by conversation/status.
- [x] CLI can show one mission by id including checkpoint data.
- [x] Missing conversation/mission reads exit non-zero with `mnemo: ... not found: <id>`.
- [x] Storage, CLI, and docs/spec contracts are updated.

## Validation
- `python3.13 -m unittest tests.test_storage.StateStoreTests.test_list_conversations_and_missions_for_continuity`
- `python3.13 -m unittest tests.test_cli.CliTests.test_conversations_and_missions_commands_inspect_continuity_ids`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest tests.test_storage`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`
- `python3 ./.trellis/scripts/task.py validate 04-25-expose-continuity-inspection-cli`
- `git diff --check`
- Temporary venv wheel build/install smoke with `tests/package_install_smoke.py`

## Technical Notes
- This is a read-only observability feature; no schema migration should be required.
- Commands should help recover `conversation_id` and `mission_id` for explicit multi-turn CLI continuity.
