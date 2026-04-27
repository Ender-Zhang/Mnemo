# Memory Health Eval Gates

## Goal
Add deterministic harness coverage for memory health risks so future changes cannot regress wrong-memory suppression, over-personalization guardrails, or compact health-review surfaces.

## Requirements
- Add a local `memory-health` harness suite that exercises memory-health behavior without provider/network calls.
- Cover wrong-memory suppression around tombstones, low-confidence over-personalization candidates, conflict/no-promotion behavior, and compact health reports.
- Include the suite in release gates if it remains deterministic and fast.
- Keep outputs compact: no raw transcripts, full evidence bodies, or page bodies in harness reports.
- Update design, checklist, and backend memory contracts to match the implemented surface.

## Acceptance Criteria
- [x] `EvalHarness().run_suite("memory-health")` passes locally.
- [x] `mnemo harness eval memory-health --json` returns a compact passing suite report.
- [x] `mnemo harness release --json` includes the new memory-health gate and passes.
- [x] Unit/CLI tests cover suite listing, eval output, release aggregation, and at least one failure-sensitive assertion shape.
- [x] Design/checklist/spec docs describe the shipped behavior without adding a fixed memory workflow.

## Technical Notes
- Reuse existing `MemoryEngine`, `StateStore`, and `EvalHarness` patterns.
- Keep cases deterministic and dependency-free.
- Prefer assertions over mock model behavior; the point is guarding memory contracts, not provider quality.
