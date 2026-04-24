# Implement Skill Review Lifecycle

## Goal
Add a lightweight review gate for generated skill candidates so Mnemo can move skill proposals from `draft` to `ready` or `blocked:*` before promotion, without introducing a rigid workflow.

## Requirements
- Add `SkillService.review(name)` to validate a generated skill candidate.
- Add a provider-native `skill_review_candidate` tool.
- Add a CLI `skills review` command for local harness inspection.
- Persist review outcomes by updating skill status.
- Keep promotion explicit and compatible with existing skill workflows.
- Update tests, specs, checklist, and Trellis task state.

## Acceptance Criteria
- [x] Structurally valid draft skills can be reviewed to `ready`.
- [x] Invalid generated skills are marked `blocked:*` with errors.
- [x] Negative usage evidence can block a candidate.
- [x] `skill_review_candidate` exposes compact tool summary/evidence.
- [x] CLI review command works with JSON output.
- [x] Focused and full tests pass.
- [ ] Git is committed and pushed.

## Technical Notes
- Review does not auto-promote a skill.
- The model remains responsible for proposing and reviewing candidates through native tool calls.
- Promotion remains an explicit action that writes `SKILL.md`.
