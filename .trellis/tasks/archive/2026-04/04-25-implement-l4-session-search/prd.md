# Implement L4 Session Search

## Goal
Add the first production slice of L4 cross-session recall so Mnemo can search raw conversation messages by bounded snippets without dumping full transcripts into prompt context.

## Requirements
- Persist user and assistant messages for each run as session-searchable records tied to conversation, mission, and run ids.
- Add SQLite FTS5-backed search over stored messages, with a safe fallback if FTS5 is unavailable.
- Expose session recall through `MemoryEngine.search(..., search_scope="sessions")` and the `memory_search` tool.
- Keep default memory search lightweight and backwards compatible.
- Add CLI support for `mnemo memory search --scope sessions` and JSON/plain output.
- Update design implementation checklist and backend specs to reflect this L4 slice.

## Acceptance Criteria
- [x] New runs persist user and assistant messages in L4 search storage.
- [x] Session search returns compact snippets with role, conversation_id, mission_id, run_id, and message_id.
- [x] `memory_search` can target stable memory, sessions, or all scopes.
- [x] CLI can search sessions without exposing full transcripts.
- [x] Existing memory/page/candidate search behavior remains compatible.
- [x] Storage migrations and tests cover fresh and upgraded state directories.

## Validation
- `python3.13 -m unittest tests.test_storage`
- `python3.13 -m unittest tests.test_memory`
- `python3.13 -m unittest tests.test_tools`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`
- `python3 ./.trellis/scripts/task.py validate 04-25-implement-l4-session-search`
- `git diff --check`

## Technical Notes
- This task implements the bounded L4 text search foundation, not vector search, RRF/MMR, tombstones, or full QueryPlanner.
- Use FTS5 where available. If SQLite lacks FTS5, fall back to bounded `LIKE` search so installed smoke and local environments still work.
