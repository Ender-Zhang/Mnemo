# Generated Tool Rollback Foundation

## Goal
Add an explicit rollback path for installed generated tools so model-led tool evolution can disable a bad generated tool without deleting candidate history or re-enabling it as immediately installable.

## Requirements
- Add a `ToolEvolutionService.rollback_generated_tool()` operation.
- Expose rollback as a provider-native tool call.
- Expose rollback through `mnemo tools rollback`.
- Keep rollback compact and reversible through the existing candidate review gate.
- Do not add a new workflow engine, scheduler, or database table.

## Acceptance Criteria
- [x] Rolling back an installed generated tool sets the generated tool status to `rolled_back`.
- [x] The source tool candidate is marked `rolled_back` and must be reviewed again before reinstall.
- [x] The active registry drops the generated tool after rollback.
- [x] CLI and ToolHarness rollback outputs stay compact and normalize missing-tool errors.
- [x] Tool evolution specs, checklist, and design docs mention the rollback foundation.

## Technical Notes
- `uninstall` remains a normal user disable that returns the candidate to `ready`.
- `rollback` is a safety action after a bad activation; it preserves history and blocks direct reinstall until `review_candidate()` runs again.
