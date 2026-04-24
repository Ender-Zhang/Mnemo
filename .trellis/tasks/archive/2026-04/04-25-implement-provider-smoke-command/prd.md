# Implement Provider Smoke Command

## Goal

Add a lightweight CLI smoke test for user-provided provider endpoints so local OpenAI-compatible deployments can be checked without writing secrets to disk.

## Scope

- Add `mnemo config smoke`.
- Reuse existing config/env resolution and provider validation.
- For OpenAI-compatible providers, call `/models` first, then `/chat/completions`.
- For Anthropic providers, run a minimal Messages API chat smoke.
- Return compact JSON/human output with redacted config and no API key leakage.
- Cover success and failure with fake-server tests.
- Update implementation checklist and code specs.

## Acceptance

- [x] `config smoke` accepts the same provider/base-url/model/api-key/api-key-env/timeout/config flags as `config inspect`.
- [x] OpenAI-compatible smoke checks `/models` and chat completion.
- [x] Anthropic smoke checks chat completion.
- [x] JSON output includes provider, model, models check status, chat check status, response preview, and redacted config.
- [x] API keys are never printed.
- [x] Provider status/payload/timeout errors produce non-zero CLI exits through existing error normalization.
- [x] Full unit suite passes.
- [x] Changes are committed locally.
