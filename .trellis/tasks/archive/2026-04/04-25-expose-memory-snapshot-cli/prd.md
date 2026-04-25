# Expose Memory Snapshot CLI

## Goal
Expose the existing L1 memory snapshot through the CLI so humans and harnesses can inspect the cache-friendly daily memory context that runtime prompt assembly uses.

## Requirements
- Add `mnemo memory snapshot [--state-dir DIR] [--json]`.
- Load the existing `wiki/l1-memory-snapshot.json` through `MemoryEngine.load_l1_snapshot()`.
- Keep the command read-only; snapshot refresh remains owned by `mnemo dream run` / `MemoryEngine.compile_l1_snapshot()`.
- JSON output returns `{"snapshot": <snapshot|null>, "exists": bool}`.
- Non-JSON output prints a compact summary and item rows without full page bodies.
- Update README, backend memory/prompt contracts, implementation checklist, and CLI regression tests.

## Acceptance Criteria
- [x] Missing or invalid snapshot exits zero and reports `exists=false`.
- [x] JSON output includes the loaded snapshot when present.
- [x] Non-JSON output shows `page_count` and compact item rows.
- [x] Snapshot output stays compact and does not include full stable memory page bodies beyond stored summaries.
- [x] Source unit tests and Trellis task validation pass.

## Validation Notes
- `python3.13 -m unittest tests.test_cli.CliTests.test_memory_snapshot_command_reads_compiled_l1_snapshot`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`
- `task.py validate 04-25-expose-memory-snapshot-cli`
- Temporary venv `pip wheel` install smoke with `tests/package_install_smoke.py`

## Technical Notes
- This is an observability command for KV-cache-first prompt context.
- Do not add a new snapshot generation workflow or mutate memory state.
- Use existing `MemoryEngine.load_l1_snapshot()` and `_print_memory_result()` patterns.
