# Normalize CLI Memory Candidate Errors

## Goal
Convert expected `memory promote` and `memory reject` candidate lookup failures into normalized CLI errors instead of Python tracebacks.

## Requirements
- Catch expected `ValueError` failures from memory curation commands at the CLI boundary.
- Re-raise those failures as `MnemoError` so top-level CLI output is `mnemo: <message>`.
- Preserve successful `memory search`, `promote`, and `reject` behavior.
- Add CLI regression coverage for missing candidate ids.
- Update error handling spec and implementation checklist.

## Acceptance Criteria
- [x] `mnemo memory promote <missing>` exits non-zero without traceback.
- [x] `mnemo memory reject <missing>` exits non-zero without traceback.
- [x] CLI stderr includes the normalized memory candidate error message.
- [x] Targeted and full tests pass.

## Technical Notes
- This is a CLI boundary normalization task.
- Do not change the memory engine consolidation semantics.
