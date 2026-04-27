# Proactive Watch Feedback Gates

## Goal
Add a lightweight Watch feedback and policy-update capability so proactive checks can learn from outcomes through model decisions, then cover the behavior with the `proactive-watch` harness suite.

## Requirements
- Reuse `scheduled_items` metadata instead of adding a heavy workflow or new scheduler table.
- Let a model/tool caller record compact Watch feedback outcomes.
- Let the caller include an explicit policy decision such as keep, sparsify, pause, or disable.
- Apply policy decisions through `ScheduleService` and `StateStore`, not direct SQLite access from CLI/MCP/tool handlers.
- Expose the capability through CLI, MCP, and provider-native tool surfaces.
- Add a deterministic `proactive-watch` harness case for repeated no-feedback evidence leading to sparse or silent Watch behavior.

## Acceptance Criteria
- [x] `ScheduleService.record_watch_feedback()` records counts/streaks and applies supplied policy decisions.
- [x] `mnemo schedule feedback ... --json` returns the updated scheduled item and compact feedback summary.
- [x] MCP exposes `mnemo_watch_feedback`.
- [x] The provider tool registry exposes `watch_feedback`.
- [x] `mnemo harness eval proactive-watch --json` passes.
- [x] The release gate includes the new deterministic proactive-watch suite.
- [x] Tests cover scheduler, storage/API boundary, CLI, MCP, tools, and harness behavior.
- [x] Checklist/spec/docs reflect the new runnable foundation and remaining limits.

## Technical Notes
- The service must not infer a complex notification workflow; it only records evidence and applies the model/user supplied decision.
- No raw notification bodies or transcripts should be stored in feedback metadata.
