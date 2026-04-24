# Implement Skill Evolution Eval Suite

## Goal
Add harness-level regression coverage for Mnemo's skill self-evolution loop: crystallization from successful traces, deterministic eval gates, review blocking, and compact context cards.

## Requirements
- Add a built-in `skill-evolution` eval suite.
- Cover successful run crystallization into a draft skill without raw payload leakage.
- Cover eval pass plus review transition to `ready`.
- Cover failed or missing eval gates that block review.
- Cover usage-driven ranking and compact skill cards without full bodies.
- Expose the suite through existing `harness eval` and `harness list`.

## Acceptance
- [x] `EvalHarness().run_suite("skill-evolution")` passes.
- [x] `list_suites()` includes `skill-evolution`.
- [x] CLI `mnemo harness eval skill-evolution --json` passes.
- [x] Tests assert the suite's key assertion names.
- [x] Implementation checklist and skill-evolution spec are updated.
- [x] Changes are committed and pushed.
