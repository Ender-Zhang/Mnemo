# Implement Eval Harness Foundation

## Goal

Add a lightweight harness that can run core personalization and replay smoke cases against Mnemo's deterministic runtime.

## Scope

- Add built-in `personalization-core` golden cases.
- Validate responses, tool calls, ChatEvent types, memory search results, and JSONL replay traces.
- Expose `mnemo harness eval`, `mnemo harness smoke`, and `mnemo harness replay`.
- Keep reports structured and compact for CLI/CI use.
- Add unit and CLI tests.

## Non-Goals

- No model-judge scoring.
- No multi-provider benchmark matrix.
- No generated skill/tool promotion gate in this task.
- No database schema migration.
