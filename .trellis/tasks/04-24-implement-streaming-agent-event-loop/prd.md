# Implement Streaming Agent Event Loop

## Goal

Extend the runnable Mnemo foundation with a stable event stream contract for chat UI, CLI, action display, and future provider-native tool-call adapters.

## Requirements

- Add a typed `ChatEvent` model with stable JSON serialization.
- Stream user-visible lifecycle events: run start, assistant text delta, tool call start/result, action card, run completion, and error.
- Keep provider-native semantics: adapters emit normalized tool call envelopes at the boundary; Mnemo does not introduce a private action DSL.
- Preserve current deterministic local runtime and make it available as a streaming adapter.
- Add provider adapter interfaces for future OpenAI/Anthropic implementations without requiring API keys now.
- Persist event stream milestones to RunLedger so runs remain replayable.
- Add CLI support for newline-delimited JSON event streaming while keeping existing synchronous output.
- Cover streaming behavior, CLI streaming, and tool event ordering with tests.

## Acceptance Criteria

- `mnemo run "remember: ..." --stream` prints valid NDJSON `ChatEvent` objects.
- Streaming output includes action/tool events before the final completion event.
- Existing `mnemo run --json` and plain text modes keep working.
- Local runtime uses the same tool harness as synchronous mode.
- Tests pass with no network access.
