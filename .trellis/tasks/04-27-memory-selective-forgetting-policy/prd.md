# Memory Selective Forgetting Policy

## Goal
Close the memory design gap for non-private selective forgetting by giving the existing memory curation path lightweight semantics for low-usefulness archival and replacement links, without adding a new workflow router.

## Requirements
- Extend existing memory tombstone/curation behavior rather than introducing a separate fixed workflow.
- `low_usefulness` should archive memory out of active recall/L1 while keeping compact curation provenance.
- `superseded` may record an optional replacement memory id and a compact `superseded_by` link.
- CLI and provider-native `memory_tombstone` must accept the optional replacement id.
- Tool, CLI, tombstone metadata, and health output must stay compact.
- Keep current `superseded` status behavior compatible with existing tests.

## Acceptance Criteria
- [x] Page tombstone with `reason=low_usefulness` marks the page `archived:low_usefulness`, removes it from active recall/L1, and writes a tombstone row.
- [x] Candidate tombstone with `reason=low_usefulness` marks the candidate `archived:low_usefulness` and writes a tombstone row.
- [x] Page/candidate tombstone with `--replacement-id` stores compact replacement metadata and writes a `superseded_by` memory link.
- [x] `memory_tombstone` tool schema and compact evidence include optional replacement metadata without large payloads.
- [x] CLI JSON/plain output exposes replacement metadata where present and keeps missing-id errors normalized.
- [x] Memory specs, tool specs, design docs, and implementation checklist are aligned.

## Technical Notes
- This task should reuse `MemoryEngine.tombstone_memory()` and `StateStore.add_memory_tombstone()`.
- No SQLite schema migration is expected; use existing memory links and tombstone metadata.
- Keep `private_delete` as the explicit redaction path; this task must not alter private-delete behavior.
