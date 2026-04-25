# Expose Memory Read CLI

## Goal
Expose the existing memory read capability through the CLI so humans and harnesses can inspect a memory candidate or stable memory page by id without using model tools or direct storage access.

## Requirements
- Add `mnemo memory read <id> [--state-dir DIR] [--json]`.
- Read both memory candidates and stable memory pages by id, matching the existing `memory_read` tool behavior.
- Return a normalized `mnemo:` error for missing memory ids without a Python traceback.
- Keep output compact for non-JSON mode and full enough in JSON mode for debugging.
- Update README, backend memory/error contracts, implementation checklist, and CLI regression tests.

## Acceptance Criteria
- [x] `mnemo memory read <candidate_id> --json` returns `{"memory": {"type": "candidate", ...}}`.
- [x] `mnemo memory read <page_id> --json` returns `{"memory": {"type": "page", ...}}`.
- [x] Non-JSON output identifies the item type, id, status, confidence, and main content.
- [x] Missing ids exit non-zero with `mnemo: memory not found: <id>` and no traceback.
- [x] Source unit tests and Trellis task validation pass.

## Validation Notes
- `python3.13 -m unittest tests.test_cli.CliTests.test_memory_read_command_reads_candidates_and_pages tests.test_cli.CliTests.test_memory_missing_candidate_errors_are_normalized`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`
- `task.py validate 04-25-expose-memory-read-cli`
- Temporary venv `pip wheel` install smoke with `tests/package_install_smoke.py`

## Technical Notes
- Reuse `StateStore.get_memory_candidate()` and `StateStore.get_memory_page()`.
- Do not add a new memory workflow or mutate memory state.
- Follow existing CLI parser/handler/test patterns in `mnemo/interfaces/cli.py` and `tests/test_cli.py`.
