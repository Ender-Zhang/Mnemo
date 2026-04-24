# Implement Skill Eval Harness

## Goal
Add a lightweight skill eval harness so model-proposed skill candidates can be validated by explicit eval cases before or during review.

## Requirements
- Reuse the existing generic `eval_cases` table instead of adding a skill-only table.
- Support skill-targeted eval cases through fields such as `skill_name`, `skill_candidate`, or `name`.
- Add a `SkillService.run_eval_case(case_id)` method that evaluates simple structured assertions against a skill body/description and records `passed` or `failed`.
- Add a provider-native `skill_run_eval_case` tool.
- Add a CLI `skills eval <case_id>` command for local harness inspection.
- Integrate linked skill eval cases into `SkillService.review`.
- Update tests, specs, checklist, and Trellis task state.

## Acceptance Criteria
- [x] Skill eval cases can pass and persist result payloads.
- [x] Failed skill eval cases persist errors.
- [x] Skill review blocks linked failed evals.
- [x] Skill review blocks linked eval cases when none passed.
- [x] `skill_run_eval_case` returns compact tool evidence.
- [x] CLI skill eval command works with JSON output.
- [x] Focused and full tests pass.
- [ ] Git is committed and pushed.

## Technical Notes
- Eval cases are model-proposed structured assertions; this does not introduce a hard workflow router.
- Supported assertion keys should stay small and deterministic: body/description contains, body forbids, and minimum body length.
