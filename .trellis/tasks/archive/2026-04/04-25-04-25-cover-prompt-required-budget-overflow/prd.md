# Cover Prompt Required Budget Overflow

## Goal
Add regression coverage for prompt assembly when optional blocks have all been dropped but required blocks still exceed the token budget.

## Requirements
- Assert non-droppable blocks remain present under an unrealistically tiny budget.
- Assert optional prompt blocks are dropped before the overflow condition is reported.
- Assert `metadata()["budget_exceeded"]` is `True` when required blocks alone exceed the budget.
- Update the prompt assembly contract and implementation checklist.

## Acceptance Criteria
- [x] Prompt test covers required-block overflow after optional drops.
- [x] Prompt assembly spec points to the concrete test file for this case.
- [x] Checklist records the landed regression coverage.
- [x] Targeted and full test suites pass.

## Technical Notes
- This task should not change prompt assembly behavior unless the test exposes a bug.
- Keep provider-native tool schema handling unchanged.
