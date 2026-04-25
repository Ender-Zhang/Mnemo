# Normalize CLI Skill Service Errors

## Goal
Convert expected skill command service failures into normalized CLI errors instead of Python tracebacks.

## Requirements
- Catch expected `ValueError` failures from skill service commands at the CLI boundary.
- Re-raise those failures as `MnemoError` so stderr is `mnemo: <message>`.
- Preserve successful `skills scan`, `view`, `review`, `eval`, `promote`, and `crystallize` behavior.
- Add CLI regression coverage for missing skill, eval case, and run ids.
- Update error handling spec and implementation checklist.

## Acceptance Criteria
- [x] `mnemo skills promote <missing>` exits non-zero without traceback.
- [x] `mnemo skills eval <missing>` exits non-zero without traceback.
- [x] `mnemo skills crystallize <missing-run> <name>` exits non-zero without traceback.
- [x] CLI stderr includes normalized skill service error messages.
- [x] Targeted and full tests pass.

## Technical Notes
- This is a CLI boundary normalization task.
- Do not change skill lifecycle or generated `SKILL.md` promotion semantics.
