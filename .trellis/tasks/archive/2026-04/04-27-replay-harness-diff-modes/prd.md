# Replay Harness Diff Modes

## Goal
Extend the existing replay summary into a compact replay report that supports deterministic, dry-run, and live-tools drift checks against RunLedger traces.

## Requirements
- Keep replay as a harness/diagnostic service; do not add a second runtime loop.
- Deterministic mode must compare JSONL trace records with persisted RunLedger events and expose prompt/tool/memory/skill/output fingerprints.
- Dry-run mode must reconstruct prompt and tool approval surfaces from the trace without calling the model or tools.
- Live-tools mode must only re-run a conservative read-only tool safelist and skip side-effecting tools.
- CLI `mnemo replay` and `mnemo harness replay` must expose mode selection and optional run-to-run comparison.
- Reports must remain compact and avoid raw prompt bodies, full transcripts, or raw tool result blobs.

## Acceptance Criteria
- [x] `replay_summary()` accepts replay mode and compare run id while preserving existing default fields.
- [x] Deterministic reports include trace/store mirror checks and category diffs.
- [x] Dry-run reports include reconstructed prompt/tool approval paths.
- [x] Live-tools reports compare safe read-only tool outputs and skip unsafe tool calls.
- [x] CLI tests cover deterministic, dry-run, live-tools, and invalid/missing replay paths.
- [x] Specs and checklist reflect the landed replay-mode foundation.

## Technical Notes
- Use existing RunLedger, StateStore, and ToolRegistry services.
- Live tool replay must not execute write, external, admin, or skill usage-mutating tools.
