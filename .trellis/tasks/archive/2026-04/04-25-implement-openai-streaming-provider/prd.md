# Implement OpenAI Streaming Provider

## Goal

Support OpenAI-compatible SSE streaming so Mnemo can emit assistant deltas as the model produces them while preserving native tool-call handling.

## Scope

- Send `stream: true` when the CLI/runtime is in stream mode.
- Parse OpenAI-compatible `data:` SSE chunks.
- Yield text deltas incrementally.
- Accumulate streamed tool call chunks into existing `ToolCallEnvelope` objects.
- Keep non-streaming behavior unchanged.
- Add provider and runtime tests for streaming text and streamed tool calls.

## Non-Goals

- No Anthropic adapter.
- No retry/cancellation redesign.
- No frontend transport server in this task.
