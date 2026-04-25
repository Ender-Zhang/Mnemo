# Expose Memory Links CLI

## Goal
Expose existing memory graph link/backlink lookup through the CLI so humans and harnesses can inspect associative memory relationships without direct SQLite access.

## Requirements
- Add `mnemo memory links <memory_id> [--direction outgoing|incoming|both] [--state-dir DIR] [--json]`.
- Reuse `StateStore.list_memory_links()` and `StateStore.list_memory_backlinks()`.
- Keep the command read-only; do not add link mutation commands.
- Return compact non-JSON rows showing direction, relation, source, target, and weight.
- Include typed JSON payloads with `outgoing` and `incoming` lists.
- Update README, backend memory/database contracts, implementation checklist, and CLI regression tests.

## Acceptance Criteria
- [x] `mnemo memory links <id> --json` returns outgoing and incoming link lists by default.
- [x] `--direction outgoing` returns only links where `<id>` is the source.
- [x] `--direction incoming` returns only backlinks where `<id>` is the target.
- [x] Non-JSON output prints compact rows with relation and weight.
- [x] Source unit tests and Trellis task validation pass.

## Validation Notes
- `python3.13 -m unittest tests.test_cli.CliTests.test_memory_links_command_reads_outgoing_and_incoming_edges`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`
- `task.py validate 04-25-expose-memory-links-cli`
- Temporary venv `pip wheel` install smoke with `tests/package_install_smoke.py`

## Technical Notes
- This is an observability command for the LLM Wiki/associative memory graph.
- It should not validate that the id exists, because links can originate from candidates or pages and an empty result is a useful answer.
- Do not introduce a new memory workflow or storage schema.
