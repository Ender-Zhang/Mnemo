# Integration Contracts

## Scenario: MnemoCore SDK And API Schema

### 1. Scope / Trigger
- Trigger: changes to `mnemo/sdk/`, integration schema payloads, public SDK methods, or CLI API schema commands.
- Goal: keep external integrations compact, language-neutral, and backed by existing runtime services instead of a parallel workflow.

### 2. Signatures
- `mnemo.sdk.MnemoClient(state_dir=DEFAULT_STATE_DIR, workspace_root=None)`
- `MnemoClient.context(intent="", *, agent_role="general", budget_tokens=4000, include_associations=True, prompt_mode="full") -> dict[str, Any]`
- `MnemoClient.recall(seed: str, *, depth=2, context="", limit=8) -> dict[str, Any]`
- `MnemoClient.capsule(task: str, *, runtime="external", agent_type="general", requested_pages=None, allowed_pages=None, conversation_id=None, mission_id=None, limit=8) -> dict[str, Any]`
- `MnemoClient.external_run(task: str, *, command: list[str] | tuple[str, ...], runtime="external-command", agent_type="general", requested_pages=None, allowed_pages=None, conversation_id=None, mission_id=None, timeout_s=30.0) -> dict[str, Any]`
- `MnemoClient.schedule_dream(*, schedule="daily", title=None, next_run_at=None, limit=20, min_confidence=0.7, source="sdk") -> dict[str, Any]`
- `MnemoClient.runtime_status(*, limit=10) -> dict[str, Any]`
- `MnemoClient.run(message: str, *, conversation_id=None, mission_id=None, prompt_mode="full") -> dict[str, Any]`
- `MnemoClient.replay(run_id: str) -> dict[str, Any]`
- `replay_summary(state_dir: str | Path, run_id: str, *, mode: str = "deterministic", compare_run_id: str | None = None) -> dict[str, Any]`
- `MnemoClient.evaluate(suite="smoke", *, variants: list[str] | tuple[str, ...] | None = None, release_gate: bool = False) -> dict[str, Any]`
- `mnemo.sdk.mnemo_core_api_schema() -> dict[str, Any]`
- CLI: `mnemo api schema [--json]`
- CLI: `mnemo api capsule TASK... [--runtime RUNTIME] [--agent-type TYPE] [--requested-page ID] [--allowed-page ID] [--state-dir DIR] [--json]`
- CLI: `mnemo api external-run TASK... --command-json '[...]' [--runtime RUNTIME] [--agent-type TYPE] [--requested-page ID] [--allowed-page ID] [--timeout-s S] [--state-dir DIR] [--json]`
- CLI: `mnemo replay RUN_ID [--mode deterministic|dry-run|live-tools] [--compare-run-id RUN_ID] [--json]`
- CLI: `mnemo harness replay RUN_ID [--mode deterministic|dry-run|live-tools] [--compare-run-id RUN_ID] [--json]`
- CLI: `mnemo api serve [--host HOST] [--port PORT] [--state-dir DIR]`

### 3. Contracts
- The SDK is a reference in-process binding; it must not introduce a second runtime loop.
- `context()` reuses `PromptAssembler`, `MemoryEngine`, `SkillService`, `ToolRegistry`, and ToolBundle metadata.
- `context()` returns prompt-ready `messages` plus `text`, compact metadata, tool bundle metadata, and compact memory/skill cards.
- `context()` must not expose raw provider-native tool schemas in metadata or tool bundle payloads.
- `context(prompt_mode="none")` is rejected because `none` is diagnostic-only.
- `recall()` reuses memory query planning and returns compact associative cards without raw evidence or full transcripts.
- `capsule()` builds a minimal-disclosure `context_capsule` for external runtimes; it exposes task, mission brief, persona-min, L1-style pointers, allowed page summaries, retention policy, and return contract.
- `capsule()` must not expose full Soul, full memory page bodies, full session transcripts, raw tool schemas, or full skill bodies.
- `requested_pages` not present in `allowed_pages` remain pointer-only; missing or inactive page ids are reported as unresolved instead of failing.
- `external_run()` creates/resolves normal conversation and mission state, builds a `context_capsule`, passes a `runtime_adapter_request` JSON envelope to an explicit argv command over stdin, and returns `external_runtime_result`.
- `external_run()` accepts only proposal fields: `summary`, `evidence`, `files_changed`, `artifact_patches`, `memory_observations`, `skill_patches`, `open_questions`, and `confidence`.
- `external_run()` records proposal events in RunLedger and ignores non-proposal fields with `runtime.boundary_violation`; it must not directly mutate stable memory, skills, generated tools, schedules, or artifacts from external output.
- `external_run()` records compact command lifecycle events without storing raw stdout/stderr bodies in the SDK result.
- `run()` executes through `run_local()` and returns run ids, response, compact `tool_summary`, and chat `event_summary`.
- `replay()` reuses `replay_summary()`.
- `replay_summary(mode="deterministic")` compares JSONL trace records with persisted RunLedger events and returns compact prompt/tool/memory/skill/output fingerprints.
- `replay_summary(mode="dry-run")` reconstructs prompt metadata and tool approval paths from the trace without calling models or tools.
- `replay_summary(mode="live-tools")` only re-executes a conservative read-only tool safelist and skips write/external/admin or read tools with known state mutation side effects.
- Replay reports include `passed`, `checks`, `fingerprint`, and `diff`; they must not include raw prompt bodies, full transcripts, or raw tool result blobs.
- `compare_run_id` compares compact category fingerprints and fails the report when prompt/tool/memory/skill/output categories drift.
- `evaluate()` reuses `EvalHarness`; without variants it returns the normal suite report.
- `evaluate(..., variants=[...])` returns the harness variant report for `no_memory`, `skills_only`, and/or `full_mnemo`.
- `evaluate(release_gate=True)` returns the fixed core release gate report across personalization, memory-safety, skill-evolution, proactive-watch, and external-harness gates; it cannot be combined with `variants`.
- `schedule_dream()` creates a durable Dream scheduled item through `ScheduleService.add_dream()` and returns compact scheduled item metadata only.
- `schedule_dream()` is a trigger/budget registration surface; it must not run Dream maintenance directly or return Dream report bodies.
- `runtime_status()` returns compact queue stats, recent run cards, open Inbox cards, generated-tool counts, and scheduled-item stats.
- `runtime_status()` is read-only and must not expose raw run input/output bodies, prompt text, traces, artifact bodies, or tool result blobs.
- `mnemo_core_api_schema()` returns a JSON-serializable language-neutral contract for `context`, `recall`, `capsule`, `external_run`, `schedule_dream`, `runtime_status`, `run`, `replay`, and `evaluate`.
- The `evaluate` API schema exposes an optional `variants` array with the public harness variant enum.
- The `evaluate` API schema exposes `release_gate` as an optional boolean.
- `mnemo api schema --json` wraps the schema as `{ "api_schema": ... }`; text mode prints readable method summaries.
- `mnemo api serve` runs the stdlib HTTP server and exposes the same core API through `/api/core/*`.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| SDK import from package | Installed wheel exposes `mnemo.sdk.MnemoClient` and schema | `tests/package_install_smoke.py` |
| Context request | Prompt-ready messages and compact metadata without raw schemas | `tests/test_sdk.py` |
| Recall request | Compact associative cards with query plan and no raw evidence | `tests/test_sdk.py` |
| Capsule request | Compact external-runtime capsule with pointer-only blocked pages and no raw state | `tests/test_sdk.py` |
| External runtime request | Explicit command receives capsule and returns proposals only; ignored fields become boundary violations | `tests/test_runtime_external.py`, `tests/test_sdk.py` |
| Dream schedule request | SDK registers a compact Dream scheduled item through existing scheduler service | `tests/test_sdk.py` |
| Runtime status request | SDK returns compact read-only status cards without raw run bodies | `tests/test_sdk.py` |
| Run request | Existing runtime creates run ledger and compact tool summary | `tests/test_sdk.py` |
| Replay/evaluate request | Existing harness services return compact suite, variant, and release-gate reports | `tests/test_sdk.py` |
| Replay modes | Deterministic, dry-run, live-tools, and compare reports stay compact and normalize invalid modes | `tests/test_replay.py`, `tests/test_harness.py`, `tests/test_cli.py` |
| CLI schema JSON | Returns `api_schema` with all core methods | `tests/test_cli.py` |
| CLI schema text | Prints readable method summaries | `tests/test_cli.py` |
| CLI HTTP serve help | Documents host/port/state-dir controls without starting a server | `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: add future MCP/HTTP adapters as thin transports over `MnemoClient` or the same service functions.
- Good: keep SDK return payloads compact enough for external agents to pass through context capsules.
- Good: keep live tool replay limited to read-only, non-mutating tools so diagnostics do not rewrite user state.
- Base: the first SDK implementation is local and dependency-free.
- Bad: duplicating memory search, prompt assembly, run execution, or eval logic inside SDK methods.
- Bad: letting external runtime stdout directly write memory pages, skills, generated tools, schedules, or artifact bodies.
- Bad: exposing raw tool schemas, full session transcripts, or full artifact bodies in SDK summaries.
- Bad: replaying write/external/admin tool calls while checking drift.

### 6. Tests Required
- SDK context, recall, capsule, external_run, schedule_dream, runtime_status, run/replay/evaluate, variant-report, release-gate, and schema shape tests.
- Replay mode tests for deterministic mirror checks, dry-run reconstruction, safe live-tools replay, side-effect skips, and run-to-run diffs.
- CLI schema command tests for JSON and readable output.
- Package install smoke import coverage for `mnemo.sdk`.

### 7. Wrong vs Correct
#### Wrong
- Spawn an external process from each transport and let its stdout call memory/skill/tool services directly.
- Return full external stdout, stderr, capsule text, or raw trace bodies from SDK results.

#### Correct
- Route SDK/CLI/MCP execution through `MnemoClient.external_run()` / `run_external()` so capsule building, proposal filtering, RunLedger events, and error normalization stay in one service.
- Return `external_runtime_result` with `capsule` summary, `proposal`, `ignored_fields`, ids, and exit code only.

## Scenario: MnemoCore HTTP JSON API

### 1. Scope / Trigger
- Trigger: changes to `mnemo/interfaces/web.py`, `mnemo api serve`, or HTTP transport paths under `/api/core/*`.
- Goal: provide a language-neutral HTTP binding over `MnemoClient` without creating a separate runtime workflow.

### 2. Signatures
- `build_http_server(WebServerConfig(...)) -> ThreadingHTTPServer`
- `serve_api(WebServerConfig(...)) -> None`
- `GET /api/core/schema -> { "api_schema": mnemo_core_api_schema() }`
- `GET /api/core/openapi.json -> OpenAPI 3.1.0 document`
- `POST /api/core/context`
- `POST /api/core/recall`
- `POST /api/core/capsule`
- `POST /api/core/external-run`
- `POST /api/core/schedule-dream`
- `POST /api/core/runtime-status`
- `POST /api/core/run`
- `POST /api/core/replay`
- `POST /api/core/evaluate`
- CLI: `mnemo api serve [--host HOST] [--port PORT] [--state-dir DIR]`

### 3. Contracts
- HTTP core routes are thin transports over `MnemoClient`; they must not duplicate memory search, prompt assembly, runtime execution, eval, or external command adapter logic.
- HTTP core responses wrap SDK results as `{ "method": "<method>", "result": <sdk payload> }`.
- Hyphenated paths map to snake-case API methods, for example `/api/core/external-run` maps to `external_run`.
- `/api/core/openapi.json` is compact discovery for current core methods; it is not generated client code.
- `run` mirrors SDK/local behavior; provider-backed streaming chat remains `/api/chat`.
- `external-run` requires `command` as a JSON array of non-empty strings and preserves the same proposal-only boundary as SDK/CLI/MCP.
- `schedule-dream` mirrors SDK `schedule_dream()` and validates `next_run_at` as string, number, or null at the HTTP boundary.
- `runtime-status` mirrors SDK `runtime_status()` and returns compact read-only status cards.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Core schema | `GET /api/core/schema` returns `mnemo.core_api.v1` | `tests/test_web.py` |
| OpenAPI discovery | `GET /api/core/openapi.json` lists `/api/core/external-run`, `/api/core/schedule-dream`, `/api/core/runtime-status`, and method schemas | `tests/test_web.py` |
| Core method dispatch | Context/capsule/run/external-run/schedule-dream/runtime-status route to SDK and return compact results | `tests/test_web.py` |
| Invalid JSON | Returns HTTP 400 JSON `{ "error": ... }` | `tests/test_web.py` |
| Missing required field | Returns HTTP 400 JSON without traceback | `tests/test_web.py` |
| Unknown method | Returns HTTP 404 JSON without traceback | `tests/test_web.py` |
| Package smoke | Installed wheel exposes web HTTP server builder | `tests/package_install_smoke.py` |

### 5. Good/Base/Bad Cases
- Good: add HTTP routes by extending the core method dispatcher and SDK schema together.
- Good: keep HTTP payloads compact and aligned with SDK/MCP output shapes.
- Base: stdlib HTTP server is enough for local and lightweight remote deployments.
- Bad: adding route-specific memory/runtime behavior that bypasses `MnemoClient`.
- Bad: returning raw provider tool schemas, full transcripts, or external command stdout bodies through HTTP.

### 6. Tests Required
- Web tests for schema, OpenAPI discovery, method dispatch including schedule-dream and runtime-status, compactness, and JSON error handling.
- CLI tests for `mnemo api serve --help`.
- Package install smoke coverage for `mnemo.interfaces.web`.

### 7. Wrong vs Correct
#### Wrong
- Implement `/api/core/run` by manually creating runs and tool calls in the web handler.

#### Correct
- Parse JSON, validate transport-level types, call `MnemoClient.run()`, and return the SDK payload under `result`.

## Scenario: MCP-Style Tool Server

### 1. Scope / Trigger
- Trigger: changes to `mnemo/mcp/`, `mnemo mcp ...` CLI commands, or external tool-surface contracts.
- Goal: expose Mnemo capabilities as compact model-callable tools without introducing a second agent workflow.

### 2. Signatures
- `mnemo.mcp.MnemoMcpServer(state_dir=DEFAULT_STATE_DIR, workspace_root=None)`
- `MnemoMcpServer.tools() -> list[dict[str, Any]]`
- `MnemoMcpServer.call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]`
- `MnemoMcpServer.call_tool_result(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]`
- `MnemoMcpServer.handle_json_rpc(message: dict[str, Any]) -> dict[str, Any] | None`
- `MnemoMcpServer.serve_content_length(input_stream=None, output_stream=None) -> None`
- `MnemoMcpServer.serve_jsonl(input_stream=None, output_stream=None) -> None`
- `mnemo.mcp.mcp_server_config(client="generic", command="mnemo", state_dir=DEFAULT_STATE_DIR) -> dict[str, Any]`
- MCP tool: `mnemo_dream_schedule(schedule="daily", title=None, next_run_at=None, limit=20, min_confidence=0.7, source="mcp")`
- CLI: `mnemo mcp tools [--state-dir DIR] [--json]`
- CLI: `mnemo mcp config [--client generic|claude] [--command COMMAND] [--state-dir DIR] [--json]`
- CLI: `mnemo mcp call TOOL --arguments-json JSON [--state-dir DIR] [--json]`
- CLI: `mnemo mcp serve [--state-dir DIR] [--transport content-length|jsonl]`

### 3. Contracts
- MCP is a transport/tool facade; it must reuse SDK and domain services rather than defining workflow steps.
- Tool descriptors use MCP-style `inputSchema` and annotations, plus a compact `mnemo.risk` field.
- `mnemo_context`, `mnemo_capsule`, `mnemo_external_run`, `mnemo_recall`, `mnemo_run`, `mnemo_replay`, and `mnemo_eval` route through `MnemoClient`.
- `mnemo_capsule` is read-only and returns the same minimal-disclosure `context_capsule` shape as the SDK.
- `mnemo_external_run` is `external` risk, requires an explicit command array, returns `external_runtime_result`, and preserves the same proposal-only boundary as the SDK.
- `mnemo_eval` accepts optional `variants`; when present it returns the same compact harness variant report as the SDK.
- `mnemo_eval` accepts `release_gate: true`; when present it returns the same compact release-gate report as the SDK.
- `mnemo_update` writes memory candidates and W0 working notes only; it must not mutate stable memory pages directly.
- `mnemo_search` returns compact memory cards and query-plan metadata without raw evidence blobs.
- `mnemo_skills` returns compact skill cards; full skill bodies remain behind existing skill-specific surfaces.
- `mnemo_tools` returns compact tool cards and ToolBundle metadata; it must not return raw provider input schemas by default.
- `mnemo_watch` and `mnemo_cron` create durable scheduled items through `ScheduleService`; due processing still runs through the normal daemon queue.
- `mnemo_dream_schedule` creates durable Dream maintenance scheduled items through `ScheduleService.add_dream()`; due processing runs bounded `MemoryEngine.dream_maintenance()` through the existing scheduler.
- `mnemo_watch_feedback` records compact Watch outcomes and applies an explicit model/user policy decision through `ScheduleService`.
- `mnemo_runtime_status` routes through `MnemoClient.runtime_status()` and includes compact scheduled-item status.
- JSON-RPC support covers `initialize`, `tools/list`, and `tools/call` with structured error responses.
- `mnemo mcp serve` defaults to MCP stdio `Content-Length` framing; JSONL stdio remains an explicit debug transport.
- `mcp_server_config()` is packaging metadata only; it must not start a server, mutate state, or execute external clients.
- MCP config output points to `mnemo mcp serve --state-dir <DIR>`, includes compact tool names/counts, and omits raw input schemas.
- `client="generic"` returns a portable stdio object; `client="claude"` returns a `mcpServers.mnemo` snippet.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Tool descriptors | Core tool names, `inputSchema`, and read/write annotations are present | `tests/test_mcp.py` |
| Compact reads | Context/capsule/search/recall/skills/tools do not expose raw evidence, full state, or raw input schemas | `tests/test_mcp.py` |
| External runtime call | `mnemo_external_run` executes explicit argv command and returns compact proposals with ignored fields | `tests/test_mcp.py` |
| Update writes | External facts become memory candidates and observations become W0 notes | `tests/test_mcp.py` |
| Watch/Cron/Dream calls | MCP calls create scheduled watch/cron/dream items, record Watch feedback policy, run due Dream items through the scheduler, and runtime status reports due/count metadata | `tests/test_mcp.py` |
| Runtime calls | Run/replay/eval/variant-eval/release-gate/status reuse existing services and compact results | `tests/test_mcp.py` |
| JSON-RPC | Initialize, list, call, unknown-method, JSONL serving, and Content-Length framing behave predictably | `tests/test_mcp.py` |
| Config packaging | Helper and CLI return compact client config snippets without raw tool schemas | `tests/test_mcp.py`, `tests/test_cli.py` |
| CLI | `mnemo mcp tools`, `mnemo mcp config`, `mnemo mcp call`, and both serve transports support JSON and normalized errors | `tests/test_cli.py` |
| Package install | Installed wheel exposes `mnemo.mcp.MnemoMcpServer` and `mcp_server_config` | `tests/package_install_smoke.py` |

### 5. Good/Base/Bad Cases
- Good: add new MCP tools as thin wrappers over SDK/domain services with compact outputs.
- Good: keep tool outputs model-actionable and small enough for external context capsules.
- Base: watch/cron tools register scheduled work; model-led execution happens when the daemon queue drains the due item, then the model may record feedback policy through `mnemo_watch_feedback`.
- Base: Dream scheduling registers a maintenance trigger/budget; memory promotion, decay, and tombstone decisions remain inside `MemoryEngine` and model-supplied Dream actions.
- Bad: adding provider-specific workflow routing inside the MCP server.
- Bad: returning full traces, full artifacts, raw provider schemas, or stable-memory mutations from generic update calls.

### 6. Tests Required
- Direct MCP server tests for descriptors, calls, capsule compactness, external_run, variant-eval, release-gate, scheduled watch/cron/dream, and Watch feedback surfaces.

### 7. Wrong vs Correct
#### Wrong
- Define MCP-specific external-runtime behavior that bypasses the SDK command adapter or accepts shell strings.

#### Correct
- Keep `mnemo_external_run` as a thin MCP wrapper over `MnemoClient.external_run()` with an explicit command array and compact proposal-only result.
- JSON-RPC tests for success, Content-Length framing, JSONL debug serving, and structured errors.
- CLI tests for JSON output, config packaging, serve transport selection, and error normalization.
- Package install smoke import coverage for `mnemo.mcp`.
