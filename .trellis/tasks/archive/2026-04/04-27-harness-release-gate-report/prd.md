# Harness Release Gate Report

## Goal
Add a lightweight release-gate report that aggregates the existing deterministic harness suites without introducing a new workflow engine.

## Requirements
- Reuse `EvalHarness` suite runners and variant comparison.
- Aggregate core release gates across `personalization-core`, `memory-safety`, `skill-evolution`, and `external-harness`.
- Expose the same compact report through CLI, SDK/API schema, and MCP.
- Keep payloads compact: no step details, raw evidence, transcripts, or provider schemas.
- Preserve existing suite and variant commands.

## Acceptance Criteria
- [x] `EvalHarness` can produce a `harness_release_report`.
- [x] `mnemo harness release --json` returns the release report and exits non-zero when any gate fails.
- [x] `MnemoClient.evaluate(release_gate=True)` returns the same report.
- [x] `mnemo_eval` accepts `release_gate: true`.
- [x] Tests cover harness, CLI, SDK schema, and MCP surfaces.
- [x] Checklist and integration/error specs reflect the new contract.

## Technical Notes
- The release report is a composition layer only; it must not duplicate suite case logic.
- The personalization release gate should reuse the existing `full_mnemo` variant target and its quantitative thresholds.
