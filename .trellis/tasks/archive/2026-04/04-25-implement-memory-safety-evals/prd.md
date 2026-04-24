# Implement Memory Safety Eval Suite

## Goal
Add executable memory safety regression coverage so Mnemo can prove that user-facing memory remains candidate-first, compact, conflict-aware, and free of raw payload leakage.

## Requirements
- Add a built-in eval suite for memory safety cases.
- Cover candidate-first memory writes, DreamCycle promotion/rejection boundaries, conflict handling, compact prompt-facing memory cards, and L1 snapshot payload safety.
- Keep the suite deterministic and local, using the existing eval harness and CLI.
- Avoid adding workflow routing; this is a harness capability and regression suite.
- Update specs, checklist, and Trellis task state.

## Acceptance Criteria
- [x] `harness eval memory-safety --json` passes.
- [x] Memory candidate writes do not directly create stable memory pages.
- [x] Conflicting candidates are marked for review and leave active memory unchanged.
- [x] Prompt/context memory cards and L1 snapshots omit raw evidence and full page bodies.
- [x] CLI harness list includes the memory safety suite.
- [x] Focused and full tests pass.
- [x] Git is committed and pushed.

## Technical Notes
- Reuse `EvalHarness` and add assertions only where the existing harness can remain simple.
- Prefer direct service assertions for memory-specific invariants over adding another workflow layer.
