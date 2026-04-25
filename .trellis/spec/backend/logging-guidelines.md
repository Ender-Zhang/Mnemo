# Logging Guidelines

## Scenario: Ledger-First Runtime Observability

### 1. Scope / Trigger
- Trigger: adding runtime, tool, provider, daemon, or CLI/web behavior that needs observability.
- Goal: prefer structured persisted events over ad hoc stdout logging.

### 2. Logging Surfaces
- Durable runtime trace: `RunLedger.append(run_id, event_type, payload)`.
- User-visible stream: `ChatEvent` emitted through runtime/common projection.
- CLI output: command result only, never debug logs mixed into JSON/NDJSON.
- Web output: NDJSON chat stream and explicit JSON APIs.
- Daemon state: persisted queue rows, lock state, and queue status APIs.

### 3. Contracts
- Runtime milestones should be ledger events, not bare `print()` calls.
- Tool execution must persist `tool.called`, `tool.result`, and `tool.denied` where applicable.
- Provider failures must use normalized provider errors; do not print request payloads.
- CLI commands with `--json` or `--stream` must keep stdout machine-readable.
- Diagnostic text belongs on stderr only for expected top-level command failures.
- Secrets, API keys, Authorization headers, raw provider request bodies, and full artifact bodies must not be logged.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Tool call | Ledger contains structured tool events | `tests/test_tools.py` |
| Chat stream | `chat.event` rows mirror user-visible events | `tests/test_runtime.py` |
| Provider smoke with API key | Output contains redacted config only | `tests/test_cli.py` |
| Artifact stream | Events contain metadata only; body is fetched explicitly | `tests/test_web.py` |
| Daemon recovery | Queue state records status and last error | `tests/test_daemon.py` |

### 5. Good/Base/Bad Cases
- Good: `ledger.append(run_id, "provider.completed", {"provider": ..., "tool_call_count": ...})`.
- Good: persist compact summaries/evidence for model feedback instead of raw payloads.
- Base: command-line human summaries can use `print()` when the command is not JSON/NDJSON.
- Bad: `print(config.api_key)` or logging Authorization headers.
- Bad: writing debug text to stdout during `--json` or `--stream` output.

### 6. Tests Required
- Runtime/tool changes should assert ledger event shape.
- CLI JSON/streaming changes should assert parseable stdout.
- Provider/config changes should assert secrets are redacted.
