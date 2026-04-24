# Implement Prompt Context Compression

## Goal
Add a lightweight prompt budget mechanism that preserves stable, cache-friendly prompt structure while dropping optional context when the prompt grows too large.

## Requirements
- Keep the model-facing loop provider-native: no workflow router or deterministic task branch should be introduced.
- Preserve non-droppable blocks: identity, operating principles, mission continuation, and current user turn.
- Allow optional blocks to be dropped by budget pressure while recording what was dropped.
- Compact large mission checkpoint values before estimating tokens.
- Expose budget metadata for replay, debugging, and future evals.
- Cover behavior with focused prompt unit tests.

## Acceptance Criteria
- [x] `PromptAssembler` accepts a token budget.
- [x] Optional blocks are dropped only when the budget is exceeded.
- [x] Stable and required blocks are retained.
- [x] Dropped block metadata is visible in `prompt.assembled` metadata.
- [x] Large checkpoint values are compacted in the mission continuation block.
- [x] Tests cover budgeted and non-budgeted prompt assembly.
