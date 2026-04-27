# Tombstone Aware Session Recall

## Goal
Prevent rejected or tombstoned memory from re-entering model context through L4 session recall while preserving explicit historical lookup when requested.

## Requirements
- Suppress L4 `session_message` recall results that match durable memory tombstones by default.
- Keep suppression compact and deterministic; do not add a workflow or scheduler.
- Preserve an explicit opt-in path for historical inspection through search options.
- Surface compact suppression metadata in debug/search responses so the model can decide whether to refine the query.
- Keep prompt-facing session results free of raw transcripts.

## Acceptance Criteria
- [x] Default `memory_search(search_scope="sessions")` suppresses session snippets matching tombstone summaries/rules.
- [x] `search_scope="all"` applies the same suppression to session snippets.
- [x] Explicit include-tombstoned search returns suppressed snippets for historical lookup.
- [x] CLI and tool schemas expose the opt-in flag.
- [x] Tests cover engine, CLI, and tool behavior.

## Technical Notes
- This is a retrieval policy, not physical deletion.
- Tombstones stay compact; use summaries/reasons/rules/metadata signals rather than raw page bodies.
