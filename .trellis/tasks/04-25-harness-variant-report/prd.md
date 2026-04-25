# Harness Variant Report

## Goal
Add a lightweight variant-comparison harness so Mnemo can evaluate whether memory/skills/context actually improve behavior without making evaluation a heavy workflow.

## Requirements
- Support the core variants from the design package: `no_memory`, `skills_only`, and `full_mnemo`.
- Reuse the existing deterministic local eval harness and RunLedger traces.
- Return compact metrics and gate status instead of full raw transcripts.
- Expose variant reports through CLI, SDK, and MCP eval surfaces.
- Keep normal `harness eval` behavior unchanged.

## Acceptance Criteria
- [x] `EvalHarness.run_variant_report("personalization-core")` returns per-variant suite summaries, metrics, deltas, and gates.
- [x] `mnemo harness variants personalization-core --json` returns the variant report.
- [x] SDK `MnemoClient.evaluate(..., variants=[...])` returns the same report shape.
- [x] MCP `mnemo_eval` accepts optional `variants` and returns compact reports.
- [x] Unknown variants fail with normalized CLI errors.
- [x] Checklist/spec/docs are updated to reflect the new harness foundation.

## Technical Notes
- `no_memory` uses capsule-mode execution, which exposes only task/mission/tool-safe context.
- `skills_only` uses minimal-mode execution as the current local proxy for reduced personal context.
- `full_mnemo` uses full prompt-mode execution and is the gated release variant.
