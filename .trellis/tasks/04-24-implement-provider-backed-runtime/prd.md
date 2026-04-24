# Implement Provider Backed Runtime

## Goal

Move Mnemo from deterministic-only local execution toward a real provider-backed agent loop while preserving the same ChatEvent, ToolHarness, and RunLedger contracts.

## Requirements

- Add provider configuration that can be supplied from CLI arguments or environment variables.
- Support OpenAI-compatible `/v1/chat/completions` without adding third-party dependencies.
- Never persist API keys or provider secrets in repo files, SQLite state, RunLedger payloads, or CLI output.
- Add timeout handling and clear errors for unreachable or slow providers.
- Bridge provider responses into the existing `ChatEvent` stream contract.
- Keep deterministic `local` runtime as the default and test path.
- Add CLI provider selection without breaking existing `mnemo run`, `--json`, or `--stream`.
- Add tests using local fake HTTP servers; no network dependency in automated tests.

## Acceptance Criteria

- `mnemo run "..." --provider openai-compatible --base-url ... --model ... --api-key-env ...` works against an OpenAI-compatible endpoint.
- `--stream` still emits NDJSON ChatEvent objects for provider-backed runs.
- Provider timeout returns a `run.error` event and nonzero CLI exit.
- Tests pass without using real API credentials.
