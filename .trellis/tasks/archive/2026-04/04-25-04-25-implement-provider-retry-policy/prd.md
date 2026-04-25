# Implement Provider Retry Policy

## Goal

Add a lightweight, configurable retry policy for provider HTTP calls so transient endpoint failures can recover without adding workflow routing or hiding normalized provider errors.

## Requirements

- Add retry settings to resolved runtime config and provider config.
- Expose retry settings through env/config file and CLI flags where provider timeout is already exposed.
- Retry non-streaming provider JSON requests for timeout, connection, and retryable HTTP status failures.
- Keep streaming provider calls single-attempt to avoid duplicate text/tool deltas after partial output.
- Preserve redacted config output and normalized provider exceptions.
- Update backend error-handling contracts and implementation checklist.

## Acceptance Criteria

- [x] `RuntimeConfig` resolves `retry_count` and `retry_backoff_s` from CLI/env/config file with safe defaults.
- [x] OpenAI-compatible non-streaming chat/model requests retry transient failures and then succeed.
- [x] Anthropic non-streaming requests use the same retry policy.
- [x] Non-retryable provider status errors still fail without extra attempts.
- [x] Streaming provider calls remain single-attempt.
- [x] Focused and full unit tests pass.
- [x] Trellis task validation passes.
- [x] Changes are committed locally.

## Technical Notes

- Keep defaults conservative: no retry unless explicitly configured.
- Retry policy belongs at the provider boundary, not in the agentic loop.
- No request payloads or API keys should be printed in retry errors.
