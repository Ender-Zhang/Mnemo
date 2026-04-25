# Cover Tool Evolution Missing Candidate

## Goal
Add regression coverage for missing generated-tool candidate handling so tool evolution errors stay deterministic at both service and model-facing tool layers.

## Requirements
- Cover `ToolEvolutionService.review_candidate` for missing candidate ids.
- Cover `ToolEvolutionService.install_candidate` for missing candidate ids.
- Cover model-facing `tool_review_candidate` behavior through `ToolHarness`.
- Ensure failed tool results stay compact and include `tool_error` evidence.
- Update tool evolution spec and implementation checklist.

## Acceptance Criteria
- [x] Service tests assert missing candidates raise `NotFoundError`.
- [x] Tool harness test asserts missing candidate returns failed `ToolResult`.
- [x] Tool harness failure includes compact `tool_error` evidence and no payload body.
- [x] Tool evolution spec points missing-candidate behavior to concrete tests.
- [x] Targeted and full test suites pass.

## Technical Notes
- This is coverage and contract hardening only.
- Do not change generated-tool lifecycle semantics.
