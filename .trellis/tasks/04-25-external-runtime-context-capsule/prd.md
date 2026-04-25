# External Runtime Context Capsule

## Goal
Add the minimal external-runtime boundary required by the design package: Mnemo can hand a compact task capsule to OpenClaw/Codex/ACP-like harnesses without exposing full personal memory, Soul, skill bodies, or raw transcripts.

## Requirements
- Add a dependency-free `ContextCapsuleBuilder` service for external runtime handoff.
- Capsule includes task, runtime, agent type, mission brief, persona minimum, memory pointers, allowed page summaries, retention policy, and return contract.
- Requested memory pages are only expanded when explicitly allowed; otherwise expose bounded title/summary metadata.
- Reuse existing memory, prompt, SDK, CLI, MCP, and eval services instead of creating a workflow router.
- Persist no new stable memory or skill state while building capsules.
- Add an `external-harness` eval suite that verifies the minimal-disclosure boundary.

## Acceptance Criteria
- [x] SDK exposes `MnemoClient.capsule(...)` with compact `context_capsule` output.
- [x] CLI exposes a JSON capsule command with normalized errors.
- [x] MCP exposes a read-only `mnemo_capsule` tool.
- [x] `mnemo harness eval external-harness --json` passes.
- [x] Capsule output omits full page bodies, raw transcripts, full Soul, raw tool schemas, and full skill bodies.
- [x] Checklist, specs, README, and API schema reflect the new foundation.

## Technical Notes
- This is a boundary/capsule foundation, not a full external runtime runner.
- RuntimeAdapter execution remains future work; this task creates the safe input contract and eval gate first.
