# Implement Anthropic Provider Adapter

## Goal
Add an Anthropic Messages API provider adapter so Mnemo can use Claude-compatible model/tool loops through the same normalized provider boundary as OpenAI-compatible runtimes.

## Requirements
- Implement Anthropic non-streaming and streaming response parsing.
- Convert Mnemo tool specs into Anthropic tool definitions.
- Convert Anthropic `tool_use` blocks into `ToolCallEnvelope`.
- Convert Mnemo messages, including tool results, into Anthropic Messages API payloads.
- Add CLI/runtime provider selection for `anthropic`.
- Keep provider errors normalized through existing provider error classes.
- Avoid persisting secrets.

## Acceptance
- [x] `AnthropicProviderAdapter` accepts `ProviderConfig` and implements `stream()`.
- [x] Adapter sends `x-api-key`, `anthropic-version`, model, messages, tools, and max token payloads.
- [x] Non-streaming text and tool calls are normalized to `ProviderEvent`.
- [x] Streaming text and tool calls are normalized to `ProviderEvent`.
- [x] CLI accepts `--provider anthropic` for run, web, daemon run, and config inspect.
- [x] Runtime provider tests cover Anthropic text, tool calls, stream, payload errors, and status errors.
- [x] CLI test covers Anthropic provider selection through fake server.
- [x] Implementation checklist is updated.
- [x] Changes are committed and pushed.
