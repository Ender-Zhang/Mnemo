# Implement Mnemo MVP Foundation

## Goal
Build the first runnable Mnemo backend slice from the design package. The MVP should prove the lean core: one CLI entry, durable Mission state, RunLedger events, provider-native tool-call boundaries, and model-led learning candidate plumbing.

## Requirements
- Create a Python 3.11+ package with a CLI entrypoint.
- Store durable state in SQLite under a configurable state directory.
- Implement `conversation_id` / `mission_id` / `run_id` entities and RunLedger events.
- Implement the minimal runtime container: hydrate minimal state, execute a provider/tool-loop skeleton, persist deltas.
- Provide core tool definitions with provider-safe names: `memory_search`, `memory_read`, `working_note`, `skills_list`, `skill_view`, `artifact_update`, `ask_user`.
- Provide learning candidate tools with provider-safe names: `memory_write_candidate`, `skill_propose_candidate`, `tool_propose_candidate`, `eval_propose_case`, `learning_discard`.
- Keep long-term memory writes as candidates, not direct core tools.
- Implement a deterministic local runtime path for tests and early CLI usage. Real OpenAI/Anthropic adapters can be added later behind the same tool-call contract.
- Add focused tests for schema creation, run ledger append, memory candidate write, and CLI smoke.

## Acceptance Criteria
- [x] `mnemo --help` works.
- [x] `mnemo init --state-dir <dir>` creates SQLite schema and directories.
- [x] `mnemo run "..." --state-dir <dir>` creates or continues a Mission and writes RunLedger events.
- [x] A run can call local core tools through the same internal tool-call envelope used by future provider adapters.
- [x] Learning candidate writes are recorded with evidence/provenance and do not immediately mutate L1 stable context.
- [x] Tests pass locally.

## Technical Notes
- Use the design package as the source of truth, especially `design/00`, `design/01`, `design/02`, `design/07`, `design/10`, and `design/11`.
- Prefer a small Python standard-library implementation for the first slice: `sqlite3`, `argparse`, `dataclasses`, `json`, `uuid`, `pathlib`.
- Avoid adding OpenAI/Anthropic SDK dependencies in the first slice; implement provider-neutral envelopes and a deterministic local runtime.
- Keep extension surfaces as interfaces or placeholders only.
