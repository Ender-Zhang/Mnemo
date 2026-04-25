# Implement Prompt Modes

## Goal
Add `full`, `minimal`, `capsule`, and `none` prompt modes to Mnemo prompt assembly and runtime wiring while keeping provider-native tool schemas available through the normal tool-call path.

## Requirements
- Preserve existing `full` prompt behavior.
- Add mode-specific prompt disclosure boundaries:
  - `minimal`: identity, operating principles, tool cards, mission continuation, selected workspace bootstrap, current turn.
  - `capsule`: identity, operating principles, tool cards, mission continuation, current turn.
  - `none`: identity and current turn only, marked as not execution-allowed metadata.
- Persist selected mode in `prompt.assembled`.
- Add CLI `mnemo run --prompt-mode`.
- Add tests for prompt assembly and runtime/provider propagation.

## Non-Goals
- Do not add workflow routing or semantic prompt selection rules.
- Do not remove provider-native tool schemas when visible tool cards are omitted or dropped.
