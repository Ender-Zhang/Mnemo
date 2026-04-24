# Implement SOP Crystallization From Runs

## Goal
Let the model crystallize a successful run trace into a draft skill candidate without auto-promoting it or introducing a fixed workflow router.

## Requirements
- Add a `SkillService.crystallize_from_run(...)` method that reads persisted run events.
- Add a provider-native `skill_crystallize_from_run` tool.
- Add a CLI `skills crystallize <run_id> <name>` command for local harness inspection.
- Keep crystallized skills as `draft` candidates that still need review/eval/promotion.
- Use compact run evidence only: tool names, summaries, and high-level event facts, not raw user messages or full payloads.
- Update tests, specs, checklist, and Trellis task state.

## Acceptance Criteria
- [x] A completed run with successful tool results can become a draft skill candidate.
- [x] Crystallized skill body contains compact procedure/evidence, not raw tool payloads.
- [x] Missing run or unsuccessful run is rejected.
- [x] `skill_crystallize_from_run` returns compact tool evidence.
- [x] CLI crystallize command works with JSON output.
- [x] Focused and full tests pass.
- [x] Git is committed and pushed.

## Technical Notes
- This is model-directed crystallization: the model decides when to call the tool and supplies the skill name/description.
- The generated draft remains subject to `skill_review_candidate`, `skill_run_eval_case`, and explicit promotion.
