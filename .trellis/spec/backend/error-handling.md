# Error Handling

> How errors are handled in this project.

## Scenario: Provider Boundary And Smoke Errors

### 1. Scope / Trigger
- Trigger: changes to provider adapters, CLI provider commands, CLI service-boundary errors, or external endpoint smoke checks.
- Goal: normalize expected runtime failures without leaking credentials, raw secret-bearing request payloads, or Python tracebacks.

### 2. Signatures
- `ProviderStatusError(status_code: int, body: str | None = None)`
- `ProviderTimeoutError(message: str)`
- `ProviderConnectionError(message: str)`
- `ProviderPayloadError(message: str)`
- `ProviderConfig(timeout_s: float, retry_count: int = 0, retry_backoff_s: float = 0.0, retry_status_codes=(429, 500, 502, 503, 504))`
- CLI: `mnemo config smoke --provider openai-compatible --base-url <url> --model <model> [--api-key-env ENV|--api-key KEY] [--json]`
- CLI: `mnemo config smoke --provider anthropic --base-url <url> --model <model> [--api-key-env ENV|--api-key KEY] [--json]`
- CLI: `mnemo config smoke --stream --provider openai-compatible --base-url <url> --model <model> [--api-key-env ENV|--api-key KEY] [--json]`
- CLI: `mnemo config capabilities [--provider local|openai-compatible|anthropic] [--model MODEL] [--api-key-env ENV|--api-key KEY] [--json]`
- CLI: `mnemo api capsule TASK... [--runtime RUNTIME] [--agent-type TYPE] [--requested-page ID] [--allowed-page ID] [--state-dir DIR] [--json]`
- CLI: `mnemo api external-run TASK... --command-json '[...]' [--runtime RUNTIME] [--agent-type TYPE] [--timeout-s S] [--state-dir DIR] [--json]`
- HTTP: `GET /api/core/schema`, `GET /api/core/openapi.json`, `POST /api/core/<method>`
- HTTP: `POST /api/core/schedule-dream`
- HTTP: `POST /api/core/schedule-watch`, `POST /api/core/schedule-cron`
- HTTP: `POST /api/core/runtime-status`
- CLI: `mnemo mcp config [--client generic|claude] [--command COMMAND] [--state-dir DIR] [--json]`
- CLI: `mnemo memory health [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo memory decay [--limit N] [--stale-confidence FLOAT] [--state-dir DIR] [--json]`
- CLI: `mnemo memory tombstone <memory_id> --reason REASON [--target-type auto|candidate|page] [--replacement-id ID] [--eval-run-id RUN_ID] [--state-dir DIR] [--json]`
- CLI: `mnemo memory forget <memory_id> [--reason REASON] [--target-type auto|candidate|page] [--state-dir DIR] [--json]`
- CLI: `mnemo memory tombstones [--target-id ID] [--target-type candidate|page] [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo dream run [--actions-json JSON_ARRAY] [--state-dir DIR] [--json]`
- CLI: `mnemo dream --now [--actions-json JSON_ARRAY] [--state-dir DIR] [--json]`
- CLI: `mnemo dream report [REPORT_ID|--latest] [--state-dir DIR] [--json]`
- CLI: `mnemo schedule add --kind watch|cron|dream [--schedule SCHEDULE] [--next-run-at TIME] [--json]`
- CLI: `mnemo artifacts read <artifact_id> [--json]`
- CLI: `mnemo inbox show <item_id> [--json]`
- CLI: `mnemo inbox resolve <item_id> --accept|--reject|--ignore [--json]`
- CLI: `mnemo schedule feedback <item_id> --outcome OUTCOME [--action keep|sparsify|pause|disable] [--policy-schedule SCHEDULE] [--json]`
- CLI: `mnemo schedule pause|resume|disable <item_id> [--json]`
- CLI: `mnemo conversations show <conversation_id> [--json]`
- CLI: `mnemo missions show <mission_id> [--json]`
- CLI: `mnemo runs show <run_id> [--json]`
- CLI: `mnemo events <run_id> [--json]`
- CLI: `mnemo replay <run_id> [--mode deterministic|dry-run|live-tools] [--compare-run-id RUN_ID] [--json]`
- CLI: `mnemo harness eval <suite> [--json]`
- CLI: `mnemo harness variants <suite> [--variant VARIANT] [--json]`
- CLI: `mnemo harness release [--json]`
- CLI: `mnemo harness replay <run_id> [--mode deterministic|dry-run|live-tools] [--compare-run-id RUN_ID] [--json]`

### 3. Contracts
- Provider adapters raise `ProviderStatusError` for non-2xx HTTP responses.
- `ProviderStatusError` may append a compact provider `error.message` or `message` field to the user-facing error string, but must keep the raw body only on the exception object for tests/diagnostics.
- Provider adapters raise `ProviderTimeoutError` for socket/URL timeout conditions.
- Provider adapters raise `ProviderConnectionError` for unreachable endpoints.
- Provider adapters raise `ProviderPayloadError` for invalid or non-object JSON payloads.
- Non-streaming provider JSON requests retry timeout errors, connection errors, and `retry_status_codes` up to `retry_count`.
- Streaming provider requests remain single-attempt because retrying after partial deltas can duplicate model output or tool calls.
- Retry config resolves from CLI args, config file, or `MNEMO_RETRY_COUNT` / `MNEMO_RETRY_BACKOFF_S`.
- Runtime cancellation is cooperative state, not a provider/tool error; observed cancellation completes the run with `status="cancelled"`.
- Web cancellation endpoint errors are JSON: missing `run_id` returns 400, unknown run id returns 404.
- Web chat streams must not emit a duplicate `server.error` after the runtime has already emitted a `*.error` chat event for the same failed stream.
- Web artifact endpoint errors are JSON: missing `artifact_id` returns 400, unknown artifact id returns 404; related artifact metadata must omit bodies.
- Web Inbox resolve endpoint errors are JSON: missing fields or invalid resolution return 400, unknown item id returns 404.
- Web learning memory endpoint errors are JSON: missing fields or invalid action return 400, unknown candidate id returns 404; valid actions are `accept`, `this_time`, `reject`, and `undo`.
- Web settings endpoint errors are JSON: invalid quiet-hours or runtime-provider payloads return 400, raw API key storage is rejected, and settings summaries do not expose provider secrets.
- HTTP core API errors are JSON: invalid JSON or bad fields return 400, unknown methods return 404, and expected `MnemoError` service failures map to 400 or 404 without traceback.
- HTTP `schedule-dream` validates `next_run_at` as a string, number, or null and returns compact JSON errors for invalid payload shapes.
- HTTP `schedule-watch` and `schedule-cron` validate required fields and `next_run_at` as a string, number, or null, returning compact JSON errors for invalid payload shapes.
- HTTP `runtime-status` validates `limit` as an integer and returns compact JSON errors for invalid payload shapes.
- Expected local CLI service errors are converted to `MnemoError` at the command boundary so stderr is `mnemo: <message>` without a Python traceback.
- `mnemo api capsule` normalizes service validation errors this way; argparse handles missing required `TASK`.
- `mnemo api external-run` normalizes invalid command JSON, invalid command arrays, timeout, process start, and non-zero external command failures this way; external stdout/stderr bodies are compacted and not printed by default.
- `mnemo mcp config` is read-only, validates a non-empty server command, and emits compact client config without credentials or raw tool schemas.
- `mnemo conversations show` and `mnemo missions show` normalize missing continuity ids this way.
- `mnemo runs show`, `mnemo runs cancel`, `mnemo events`, `mnemo replay`, and `mnemo harness replay` normalize missing run ids this way.
- `mnemo replay` and `mnemo harness replay` normalize unknown replay modes this way.
- `mnemo harness eval` and `mnemo harness variants` normalize unknown suites or variants this way.
- `mnemo harness release` exits non-zero when any release gate fails and keeps the report compact.
- `mnemo memory promote` and `mnemo memory reject` normalize missing memory candidates this way.
- `mnemo memory search --debug-query` remains read-only and returns compact query and recall-policy metadata without raw transcripts.
- `mnemo memory search --include-tombstoned` is an explicit historical lookup opt-in; it still returns bounded session snippets, not raw message content.
- `mnemo memory read` normalizes missing candidate/page ids this way.
- `mnemo memory tombstone` normalizes missing candidate/page ids, missing replacement ids, and missing eval run ids this way.
- `mnemo memory forget` normalizes missing candidate/page ids this way and never prints deleted memory text after redaction.
- `mnemo memory health` and `mnemo memory tombstones` are read-only inspection commands and do not require raw SQLite access.
- `mnemo memory decay` mutates active memory pages through `MemoryEngine.decay_stale_pages()` and returns compact reports without raw evidence or full page bodies.
- `mnemo dream run --actions-json` and `mnemo dream --now --actions-json` accept only valid JSON arrays of action objects; action-level service errors are reported inside the Dream report as compact skipped actions.
- `mnemo dream report <missing_id>` normalizes missing report ids this way.
- `mnemo schedule add --kind dream` uses the same schedule validation path as watch/cron and emits compact scheduled item metadata.
- `mnemo artifacts read` normalizes missing artifact ids this way.
- `mnemo inbox show` and `mnemo inbox resolve` normalize missing item ids this way.
- `mnemo schedule feedback`, `pause`, `resume`, and `disable` normalize missing scheduled item ids and invalid Watch feedback policy this way.
- `mnemo skills review`, `eval`, `promote`, and `crystallize` normalize expected service errors this way.
- `mnemo tools review`, `install`, `uninstall`, and `rollback` normalize missing candidate/generated-tool errors this way.
- `mnemo evals create` and `record` normalize missing runs/eval cases and invalid JSON payloads this way.
- `mnemo config smoke` uses the existing config/env resolver and provider validation.
- OpenAI-compatible smoke probes `/models` first, then `/chat/completions`.
- `mnemo config smoke --stream` probes chat through the provider streaming path while keeping model listing non-streaming.
- Anthropic smoke probes `/messages`; model listing is reported as skipped.
- CLI output must use redacted config and must never print the API key value.
- `mnemo config capabilities` is read-only and does not validate provider reachability.
- Expected provider errors bubble through the top-level `MnemoError` handler and produce a non-zero exit.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| OpenAI-compatible smoke succeeds | JSON includes passed models and chat checks | `tests/test_cli.py` |
| OpenAI-compatible streaming smoke succeeds | JSON includes `stream=true` and streamed chat text | `tests/test_cli.py` |
| Anthropic smoke succeeds | JSON includes skipped models and passed chat check | `tests/test_cli.py` |
| API key supplied | Request header uses key, stdout redacts it | `tests/test_cli.py` |
| Provider returns HTTP error | CLI exits non-zero and stderr includes normalized status | `tests/test_cli.py` |
| Provider status includes message | Error string includes compact provider message without raw secrets | `tests/test_providers.py` |
| Invalid provider payload | Adapter raises `ProviderPayloadError` | `tests/test_providers.py` |
| Provider timeout | Adapter raises `ProviderTimeoutError` | `tests/test_providers.py` |
| External command succeeds with unsupported fields | CLI/SDK return proposals and ignored field names without direct writes | `tests/test_cli.py`, `tests/test_runtime_external.py` |
| External command exits non-zero | CLI/SDK persist failed run and surface normalized `ExternalRuntimeError` | `tests/test_runtime_external.py` |
| Retryable provider status | Non-streaming adapter retries and can recover | `tests/test_providers.py` |
| Non-retryable provider status | Adapter fails without extra attempts | `tests/test_providers.py` |
| Streaming provider status | Streaming adapter fails without retry | `tests/test_providers.py` |
| Retry config resolution | Runtime config resolves retry fields and redacts secrets | `tests/test_config.py` |
| Capability inspection | CLI reports provider capability metadata without leaking API keys | `tests/test_cli.py` |
| Runtime cancellation | Provider runtime emits `run.completed` with cancelled status after observing the signal | `tests/test_runtime.py` |
| Web cancellation endpoint | Valid run returns cancellation payload; missing/unknown ids return JSON errors | `tests/test_web.py` |
| Web streamed runtime error | Response includes one runtime error card and no duplicate server error | `tests/test_web.py` |
| Web artifact endpoint | Valid artifact returns body plus compact related metadata; missing/unknown ids return JSON errors | `tests/test_web.py` |
| Web Inbox resolve endpoint | Valid resolve returns item payload; missing/invalid/unknown ids return JSON errors | `tests/test_web.py` |
| Web learning memory endpoint | Valid action returns compact candidate payload; missing/invalid/unknown ids return JSON errors | `tests/test_web.py` |
| Web settings endpoint | Valid runtime and quiet-hours updates return settings payloads; invalid time/runtime payloads return JSON errors; API keys are not exposed | `tests/test_web.py` |
| HTTP core API errors | Invalid JSON, missing required fields, and unknown methods return compact JSON errors | `tests/test_web.py` |
| HTTP Dream schedule errors | Invalid `next_run_at` returns compact JSON 400 without traceback | `tests/test_web.py` |
| HTTP Watch/Cron schedule errors | Missing Watch target or invalid Cron `next_run_at` returns compact JSON 400 without traceback | `tests/test_web.py` |
| HTTP runtime status errors | Invalid `limit` returns compact JSON 400 without traceback | `tests/test_web.py` |
| MCP config output | CLI returns compact generic/Claude stdio config without raw tool schemas | `tests/test_cli.py` |
| Missing continuity id in CLI show | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Missing run id in CLI trace/show/cancel | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Unknown replay mode | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Missing memory candidate in CLI curation | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Memory query debug | CLI emits compact query plan and recall-policy metadata without changing default JSON shape | `tests/test_cli.py` |
| Missing memory id in CLI read | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Missing memory id, replacement id, or eval run id in CLI tombstone | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Missing memory id in CLI forget | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Memory health/decay/tombstone listing | CLI exits zero with compact JSON or row output | `tests/test_cli.py` |
| Dream actions JSON | Valid action arrays produce compact report action counts; invalid JSON or non-array input returns `mnemo:` errors | `tests/test_cli.py` |
| Missing Dream report id | CLI exits non-zero with `mnemo:` error and no traceback | CLI behavior |
| Dream scheduled item | CLI creates and ticks a due Dream item with compact report metadata and no traceback | `tests/test_cli.py` |
| Missing artifact id in CLI read | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Missing Inbox item in CLI show/resolve | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Missing scheduled item in CLI status/feedback commands | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Missing skill/eval/run in CLI skill commands | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Missing tool candidate/generated tool in CLI lifecycle commands | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Missing run/eval case or invalid JSON in CLI eval commands | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Unknown harness suite or variant | CLI exits non-zero with `mnemo:` error and no traceback | `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: pass credentials with `--api-key-env` or `MNEMO_API_KEY`.
- Good: show response previews and model ids, not raw request payloads.
- Good: surface compact provider quota/rate-limit reasons such as `error.message`.
- Good: set `retry_count` only for transient endpoint instability and keep default at zero.
- Base: `--api-key` is supported for local smoke but is redacted in output.
- Base: streaming calls rely on timeout and normalized errors, not retries.
- Base: blocking provider calls may only observe cancellation after the provider call returns or times out.
- Base: the web stop control requests cancellation and then waits for the stream to finish.
- Base: service-layer `ValueError` is acceptable inside domain code when the CLI boundary converts it before user output.
- Bad: print Authorization headers, API keys, or full provider error bodies to stdout.
- Bad: retry streaming calls after text/tool deltas have already been emitted.
- Bad: reporting an observed user cancellation as `run.error`.
- Bad: using a single-threaded web server that blocks cancellation while `/api/chat` streams.

### 6. Tests Required
- CLI success for OpenAI-compatible smoke.
- CLI success for OpenAI-compatible streaming smoke.
- CLI success for Anthropic smoke.
- CLI failure for provider status errors.
- Existing provider adapter status/payload/timeout tests still pass.
- Provider retry tests for OpenAI-compatible and Anthropic non-streaming calls.
- Config resolver test for `retry_count` and `retry_backoff_s`.
- Runtime cancellation test for cancelled completion status.
- Web cancellation endpoint test for success and JSON error responses.
- Web artifact endpoint test for success, compact related metadata, and JSON error responses.
- Web Inbox resolve endpoint test for success and JSON error responses.
- Web learning memory endpoint test for success and JSON error responses.
- Web settings endpoint test for summary, runtime update, quiet-hours update, invalid payload errors, raw-secret rejection, and secret redaction.
- CLI conversation/mission show tests for missing ids without tracebacks.
- CLI run trace/show/cancel tests for missing run ids without tracebacks.
- CLI harness eval/variant/release tests for unknown suites or variants without tracebacks.
- CLI memory curation tests for missing candidate errors without tracebacks.
- CLI memory read tests for missing ids without tracebacks.
- CLI memory health/decay/tombstone tests for compact output, replacement links, harmful eval routing, and missing ids without tracebacks.
- CLI memory forget tests for compact private-delete output and missing ids without tracebacks.
- CLI MCP config tests for compact JSON and readable client config output.
- CLI Dream report tests for missing ids without tracebacks.
- CLI Dream action tests for valid action reports and invalid `--actions-json` without tracebacks.
- CLI artifact read tests for missing ids without tracebacks.
- CLI Inbox show/resolve tests for missing item ids without tracebacks.
- CLI schedule feedback/pause/resume/disable tests for missing item ids without tracebacks.
- CLI skill command tests for missing skill, eval case, and crystallization run errors without tracebacks.
- CLI tool lifecycle tests for missing candidate and generated tool errors without tracebacks.
- CLI eval tests for missing runs/eval cases and invalid JSON without tracebacks.

### 7. Wrong vs Correct
#### Wrong
```python
print(config.api_key)
```

#### Correct
```python
print(config.redacted()["api_key"])
```
