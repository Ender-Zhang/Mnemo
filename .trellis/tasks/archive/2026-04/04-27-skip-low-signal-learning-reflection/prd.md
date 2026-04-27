# Skip Low Signal Learning Reflection

## Goal
Avoid running after-turn learning reflection for structurally low-signal turns, while keeping model-driven learning for task trajectories that produced meaningful tool/candidate evidence.

## Requirements
- Skip provider learning reflection before the second model call when the compact learning packet has no learning candidates and fewer than three non-learning tool results.
- Persist a compact `learning.reflection.skipped` ledger event with a clear reason for skipped low-signal turns.
- Do not emit user-visible `status.updated` learning messages for skipped low-signal turns.
- Keep provider-led learning reflection unchanged for existing learning candidates and structurally complex tool-backed turns.
- Filter internal learning discard housekeeping from the visible web activity stream.
- Do not use user-message keyword lists or text-language matching for this gate.

## Acceptance Criteria
- [x] A simple "你好" style turn records `learning.packet` and `learning.reflection.skipped` but does not call the provider a second time.
- [x] A structurally complex tool-backed turn still reaches provider learning reflection.
- [x] Web activity ignores `learning_discard` completions and learning housekeeping status.
- [x] Runtime and web asset tests cover the behavior.

## Technical Notes
- Keep the guard narrow and conservative: skip zero/low-tool turns unless a learning candidate already exists.
- Do not add a separate workflow router; this is a cheap evidence guard before invoking the model-led learning reflection.
