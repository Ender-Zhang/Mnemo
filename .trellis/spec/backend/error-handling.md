# Error Handling

> How errors are handled in this project.

## Scenario: Provider Boundary And Smoke Errors

### 1. Scope / Trigger
- Trigger: changes to provider adapters, CLI provider commands, or external endpoint smoke checks.
- Goal: normalize provider failures without leaking credentials or raw secret-bearing request payloads.

### 2. Signatures
- `ProviderStatusError(status_code: int, body: str | None = None)`
- `ProviderTimeoutError(message: str)`
- `ProviderConnectionError(message: str)`
- `ProviderPayloadError(message: str)`
- CLI: `mnemo config smoke --provider openai-compatible --base-url <url> --model <model> [--api-key-env ENV|--api-key KEY] [--json]`
- CLI: `mnemo config smoke --provider anthropic --base-url <url> --model <model> [--api-key-env ENV|--api-key KEY] [--json]`

### 3. Contracts
- Provider adapters raise `ProviderStatusError` for non-2xx HTTP responses.
- Provider adapters raise `ProviderTimeoutError` for socket/URL timeout conditions.
- Provider adapters raise `ProviderConnectionError` for unreachable endpoints.
- Provider adapters raise `ProviderPayloadError` for invalid or non-object JSON payloads.
- `mnemo config smoke` uses the existing config/env resolver and provider validation.
- OpenAI-compatible smoke probes `/models` first, then `/chat/completions`.
- Anthropic smoke probes `/messages`; model listing is reported as skipped.
- CLI output must use redacted config and must never print the API key value.
- Expected provider errors bubble through the top-level `MnemoError` handler and produce a non-zero exit.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| OpenAI-compatible smoke succeeds | JSON includes passed models and chat checks | `tests/test_cli.py` |
| Anthropic smoke succeeds | JSON includes skipped models and passed chat check | `tests/test_cli.py` |
| API key supplied | Request header uses key, stdout redacts it | `tests/test_cli.py` |
| Provider returns HTTP error | CLI exits non-zero and stderr includes normalized status | `tests/test_cli.py` |
| Invalid provider payload | Adapter raises `ProviderPayloadError` | `tests/test_providers.py` |
| Provider timeout | Adapter raises `ProviderTimeoutError` | `tests/test_providers.py` |

### 5. Good/Base/Bad Cases
- Good: pass credentials with `--api-key-env` or `MNEMO_API_KEY`.
- Good: show response previews and model ids, not raw request payloads.
- Base: `--api-key` is supported for local smoke but is redacted in output.
- Bad: print Authorization headers, API keys, or full provider error bodies to stdout.

### 6. Tests Required
- CLI success for OpenAI-compatible smoke.
- CLI success for Anthropic smoke.
- CLI failure for provider status errors.
- Existing provider adapter status/payload/timeout tests still pass.

### 7. Wrong vs Correct
#### Wrong
```python
print(config.api_key)
```

#### Correct
```python
print(config.redacted()["api_key"])
```
