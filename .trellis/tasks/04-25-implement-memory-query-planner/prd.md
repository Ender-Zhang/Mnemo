# Implement Memory Query Planner Foundation

## Goal
Add a lightweight Memory QueryPlanner foundation so memory search can use explicit lexical, semantic, temporal, and dimension signals, then fuse and annotate results without introducing a separate workflow router.

## Requirements
- Add a compact query plan API to `MemoryEngine`.
- Keep default memory search behavior compatible with existing tools and CLI output.
- Use the query plan to run multiple deterministic retrieval variants and merge duplicate results.
- Annotate results with retrieval score, matched routes, temporal/dimension hints, stale/tombstone flags, and compact plan metadata.
- Expose plan inspection through `memory_search` tool results and `mnemo memory search --debug-query`.
- Update memory code-specs and implementation checklist.

## Non-Goals
- Do not add vector storage or external embedding dependencies in this task.
- Do not add a pre-run memory workflow or force memory search before every turn.
- Do not implement durable tombstone storage, decay passes, or selective forgetting in this task.

## Acceptance Criteria
- [ ] Existing memory, tool, CLI, runtime, and harness tests still pass.
- [ ] New tests cover query planning, fused retrieval, annotations, and CLI debug output.
- [ ] Memory search remains compact and omits raw session transcripts.
- [ ] Checklist reflects this as a partial QueryPlanner foundation, not full semantic/vector completion.
