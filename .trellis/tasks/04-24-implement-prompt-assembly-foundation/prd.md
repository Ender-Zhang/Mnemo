# Implement Prompt Assembly Foundation

## Goal

Introduce a lightweight Prompt Assembly foundation so Mnemo provider runs no longer send raw user text only. The first version should preserve the design principles: stable prefix, dynamic mission tail, tool cards, model-led decision making, and inspectable prompt metadata.

## Requirements

- Add `PromptBlock` and `AssembledPrompt` models.
- Add `PromptAssembler` that creates:
  - stable system identity and operating principles,
  - stable tool-use guidance,
  - mission continuation block from `Mission` checkpoint,
  - compact tool card block,
  - current user turn.
- Keep the stable prefix deterministic and cache-friendly.
- Do not add workflow routing rules; prompt text should expose capabilities and boundaries, not route tasks.
- Use assembled prompt messages in provider-backed runtime.
- Persist prompt assembly metadata to RunLedger.
- Add CLI `prompt inspect <run_id>` to view prompt blocks recorded for a run.
- Add tests for block order, cache policy, provider runtime integration, and CLI inspection.

## Acceptance Criteria

- Provider runtime sends system/developer/user messages produced by `PromptAssembler`.
- `run_events` include `prompt.assembled` with block ids, cache policy, token estimates, and dropped block summaries if any.
- `mnemo prompt inspect <run_id> --json` returns the recorded prompt assembly event.
- Tests pass without network access.
