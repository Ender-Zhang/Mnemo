# Expose Skill Usage CLI

## Goal
Expose stored skill usage and outcome signals through a lightweight CLI so humans and scripts can inspect the evidence that drives skill ranking and review decisions.

## Requirements
- Add `mnemo skills usage [name]`.
- Reuse `StateStore.list_skill_usage` and `StateStore.skill_usage_stats`; do not add a new service or workflow.
- Support `--limit` and `--json`.
- Include compact aggregate stats alongside event rows.
- Keep existing `skills` commands unchanged.

## Acceptance Criteria
- [x] `mnemo skills usage writer --state-dir ... --json` returns writer usage events and stats.
- [x] `mnemo skills usage --state-dir ... --json` returns usage events and stats for all skills.
- [x] Non-JSON output stays compact and readable.
- [x] README, backend contracts, and implementation checklist reflect the shipped CLI surface.

## Technical Notes
- This is a read-only operational surface over existing model-recorded usage/outcome signals.
- Recording outcomes remains available through the provider-native `skill_record_outcome` tool.
