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
- `MnemoClient.schedule_watch(target: str, *, instruction=None, schedule="daily", next_run_at=None, source="sdk") -> dict[str, Any]`
- `MnemoClient.schedule_cron(message: str, *, schedule="once", title=None, next_run_at=None, source="sdk") -> dict[str, Any]`
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
- `workspace_root=None` resolves to `<state_dir>/workspace` and creates it before file tools or external runtimes use it as cwd.
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
- `schedule_watch()` creates a durable Watch scheduled item through `ScheduleService.add_watch()` and returns compact scheduled item metadata only.
- `schedule_cron()` creates a durable Cron scheduled item through `ScheduleService.add_cron()` and returns compact scheduled item metadata only.
- Watch/Cron Core API registration must not enqueue or execute work directly; due processing remains owned by scheduler tick and the normal daemon queue.
- `runtime_status()` returns compact queue stats, recent run cards, open Inbox cards, generated-tool counts, and scheduled-item stats.
- `runtime_status()` is read-only and must not expose raw run input/output bodies, prompt text, traces, artifact bodies, or tool result blobs.
- `mnemo_core_api_schema()` returns a JSON-serializable language-neutral contract for `context`, `recall`, `capsule`, `external_run`, `schedule_dream`, `schedule_watch`, `schedule_cron`, `runtime_status`, `run`, `replay`, and `evaluate`.
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
| Watch/Cron schedule requests | SDK registers compact Watch and Cron scheduled items through existing scheduler service | `tests/test_sdk.py` |
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
- SDK context, recall, capsule, external_run, schedule_dream, schedule_watch, schedule_cron, runtime_status, run/replay/evaluate, variant-report, release-gate, and schema shape tests.
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
- `serve_web(WebServerConfig(...)) -> None`
- `serve_api(WebServerConfig(...)) -> None`
- `mnemo.interfaces.web._AutoDreamScheduler.tick_once(*, now: float | str | None = None) -> dict[str, Any]`
- `GET /api/core/schema -> { "api_schema": mnemo_core_api_schema() }`
- `GET /api/core/openapi.json -> OpenAPI 3.1.0 document`
- `POST /api/core/context`
- `POST /api/core/recall`
- `POST /api/core/capsule`
- `POST /api/core/external-run`
- `POST /api/core/schedule-dream`
- `POST /api/core/schedule-watch`
- `POST /api/core/schedule-cron`
- `POST /api/core/runtime-status`
- `POST /api/core/run`
- `POST /api/core/replay`
- `POST /api/core/evaluate`
- Web UI helper: `GET /api/catalog`
- CLI: `mnemo api serve [--host HOST] [--port PORT] [--state-dir DIR]`

### 3. Contracts
- HTTP core routes are thin transports over `MnemoClient`; they must not duplicate memory search, prompt assembly, runtime execution, eval, or external command adapter logic.
- `serve_web()` owns web-service background duties: it starts the stdlib HTTP server and a daemon auto Dream scheduler that ensures one default service-owned Dream item and ticks only due Dream items.
- The auto Dream scheduler must build its provider runner from live web runtime settings each tick, so settings/env changes apply without process-local rule fallback.
- The auto Dream scheduler must leave due Dream items untouched when the runtime provider is `local`; misconfigured provider-backed runs are recorded as scheduled tick failures for retry.
- HTTP core responses wrap SDK results as `{ "method": "<method>", "result": <sdk payload> }`.
- Hyphenated paths map to snake-case API methods, for example `/api/core/external-run` maps to `external_run`.
- `/api/core/openapi.json` is compact discovery for current core methods; it is not generated client code.
- `run` mirrors SDK/local behavior; provider-backed streaming chat remains `/api/chat`.
- `external-run` requires `command` as a JSON array of non-empty strings and preserves the same proposal-only boundary as SDK/CLI/MCP.
- `schedule-dream` mirrors SDK `schedule_dream()` and validates `next_run_at` as string, number, or null at the HTTP boundary.
- `schedule-watch` and `schedule-cron` mirror SDK registration methods and validate `next_run_at` as string, number, or null at the HTTP boundary.
- `runtime-status` mirrors SDK `runtime_status()` and returns compact read-only status cards.
- `/api/catalog` is a Web UI helper over `SkillService` and `ToolRegistry`; it returns compact skill cards, compact tool cards, ToolBundle metadata, and counts, but no full skill bodies and no raw tool input schemas.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Core schema | `GET /api/core/schema` returns `mnemo.core_api.v1` | `tests/test_web.py` |
| OpenAPI discovery | `GET /api/core/openapi.json` lists `/api/core/external-run`, `/api/core/schedule-dream`, `/api/core/schedule-watch`, `/api/core/schedule-cron`, `/api/core/runtime-status`, and method schemas | `tests/test_web.py` |
| Core method dispatch | Context/capsule/run/external-run/schedule-dream/schedule-watch/schedule-cron/runtime-status route to SDK and return compact results | `tests/test_web.py` |
| Web catalog | `GET /api/catalog` returns compact Skills/Tools cards and omits skill bodies/raw schemas | `tests/test_web.py` |
| Invalid JSON | Returns HTTP 400 JSON `{ "error": ... }` | `tests/test_web.py` |
| Missing required field | Returns HTTP 400 JSON without traceback | `tests/test_web.py` |
| Unknown method | Returns HTTP 404 JSON without traceback | `tests/test_web.py` |
| Package smoke | Installed wheel exposes web HTTP server builder | `tests/package_install_smoke.py` |

### 5. Good/Base/Bad Cases
- Good: add HTTP routes by extending the core method dispatcher and SDK schema together.
- Good: keep HTTP payloads compact and aligned with SDK/MCP output shapes.
- Good: keep Web UI helper routes as read-only projections over existing services with compact payloads.
- Good: keep service background jobs routed through existing scheduler/runtime services instead of route handlers.
- Base: stdlib HTTP server is enough for local and lightweight remote deployments.
- Bad: adding route-specific memory/runtime behavior that bypasses `MnemoClient`.
- Bad: letting web background Dream tick watch/cron items or run deterministic memory promotion rules.
- Bad: returning raw provider tool schemas, full transcripts, or external command stdout bodies through HTTP.

### 6. Tests Required
- Web tests for schema, OpenAPI discovery, method dispatch including schedule-dream, schedule-watch, schedule-cron, and runtime-status, compactness, and JSON error handling.
- Web tests for auto Dream scheduler default registration and provider-backed due tick behavior.
- Web tests for `/api/catalog` compactness and Skills/Tools static asset hooks.
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

## Scenario: Feishu/Lark Messaging Channel

### 1. Scope / Trigger
- Trigger: changes to `mnemo/channels/feishu.py`, `mnemo channels feishu ...`, or Feishu/Lark webhook payload handling.
- Goal: let external chat messages enter the existing Mnemo runtime without introducing a second agent loop, while keeping channel secrets local and masked.

### 2. Signatures
- `mnemo.channels.FeishuChannelConfig(...)`
- `mnemo.channels.start_feishu_qr_onboarding(domain="feishu") -> FeishuQrOnboardSession`
- `mnemo.channels.poll_feishu_qr_onboarding(session, state_dir=..., save=True) -> dict[str, Any]`
- `mnemo.channels.feishu_channel_status(state_dir) -> dict[str, Any]`
- `mnemo.channels.build_feishu_server(config: FeishuChannelConfig) -> ThreadingHTTPServer`
- `mnemo.channels.serve_feishu(config: FeishuChannelConfig) -> None`
- `FeishuClient.start_streaming_card(chat_id: str, reply_to_message_id: str = "") -> FeishuStreamingCard`
- `FeishuClient.update_streaming_card(card: FeishuStreamingCard, markdown: str) -> None`
- `FeishuClient.close_streaming_card(card: FeishuStreamingCard, markdown: str) -> None`
- CLI: `mnemo channels feishu onboard [--domain feishu|lark] [--timeout-s S] [--state-dir DIR] [--json]`
- CLI: `mnemo channels feishu status [--state-dir DIR] [--json]`
- CLI: `mnemo channels feishu serve [--connection webhook|websocket] [--streaming|--no-streaming] [--footer-status|--no-footer-status] [--footer-elapsed|--no-footer-elapsed] [--thread-session|--no-thread-session] [--host HOST] [--port PORT] [--path PATH] [--state-dir DIR] [--workspace-root DIR] [--provider local|openai-compatible|anthropic] [--base-url URL] [--model MODEL] [--api-key-env ENV]`
- HTTP: `GET /api/channels/feishu`
- HTTP: `POST /api/channels/feishu/onboard/start`
- HTTP: `POST /api/channels/feishu/onboard/poll`

### 3. Contracts
- Feishu webhook mode is a transport facade over `run_local()` / `run_provider()` and `stream_local()` / `stream_provider()`; it must not duplicate prompt assembly, memory, tools, or provider orchestration.
- Feishu credentials and channel behavior resolve from explicit flags or environment variables: `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_VERIFICATION_TOKEN`, `FEISHU_ENCRYPT_KEY`, `FEISHU_ALLOWED_USERS`, `FEISHU_BOT_OPEN_ID`, `FEISHU_BOT_NAME`, `FEISHU_STREAMING`, `FEISHU_FOOTER_STATUS`, `FEISHU_FOOTER_ELAPSED`, `FEISHU_THREAD_SESSION`, and optional `FEISHU_API_BASE_URL`.
- QR onboarding uses Feishu/Lark app registration device flow, requests `PersonalAgent` with `client_secret` auth, and stores the returned app credentials in `<state_dir>/channels/feishu_config.json`.
- The saved Feishu config is the only channel secret persistence exception; it must be state-local, mode `0600` where supported, and never returned unmasked through Web/CLI status payloads.
- Non-QR secrets must not be persisted, logged, returned in JSON, or printed by CLI help beyond variable names.
- Saved QR credentials may be used by `mnemo channels feishu serve` when flags/env vars are absent.
- Web onboarding sessions live in process memory; `/start` returns a QR URL plus optional SVG data, and `/poll` saves credentials only after Feishu returns a completed registration.
- Websocket mode is allowed when optional Feishu dependencies are installed; it still routes events into the same `FeishuChannelService`.
- URL verification payloads (`type=url_verification`) return `{ "challenge": ... }` before token/signature checks so Feishu subscription setup works.
- When configured, verification-token and signature checks use timing-safe comparison and return compact `401` responses on failure.
- Encrypted webhook payloads are rejected with compact JSON until a dependency-free decrypt path is added.
- Inbound `im.message.receive_v1` text messages are deduplicated by event/message id before runtime execution.
- Message processing runs in a background thread and returns Feishu's webhook acknowledgement quickly; Feishu fallback rich-post replies are sent through `/open-apis/im/v1/messages?receive_id_type=chat_id`.
- Assistant replies default to Feishu official streaming cards when `streaming=true`: create a CardKit card through `/open-apis/cardkit/v1/cards`, send or reply with an `interactive` card message, update the card element through `/open-apis/cardkit/v1/cards/:card_id/elements/:element_id/content`, close streaming mode through `/open-apis/cardkit/v1/cards/:card_id/settings`, then best-effort update the final card through `/open-apis/cardkit/v1/cards/:card_id` with status/elapsed footer metadata when enabled.
- Topic/thread messages use `reply_in_thread=true` and state-local conversation keys scoped by thread id when `thread_session=true`, so Feishu topic groups can run independent Mnemo conversations in the same chat.
- If streaming-card startup fails, or `--no-streaming` / `FEISHU_STREAMING=false` is set, assistant replies fall back to Feishu/Lark rich `post` messages with Markdown blocks when possible; send failures fall back to a structural rich-post conversion and error replies may remain plain text.
- Feishu inbound messages may receive a best-effort emoji reaction through `/open-apis/im/v1/messages/:message_id/reactions`; reaction failures must not block runtime processing.
- Legacy rich-post streaming is implemented by sending one invisible placeholder rich post, then editing that message through `/open-apis/im/v1/messages/:message_id` with throttled partial content and one final edit; partial edits must stay below the platform's 20-edit limit.
- Per-chat execution is serialized so a chat cannot overlap multiple Mnemo turns.
- Feishu chat ids map to Mnemo conversation ids in state-local channel metadata so follow-up messages keep continuity.
- Group messages honor the mention gate when `require_mention` is true and a bot identity is configured; DMs are accepted.
- Allowed-user filtering compares Feishu open_id, user_id, and union_id.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| URL verification | Returns the challenge JSON | `tests/test_channels.py` |
| Invalid token/signature | Returns compact 401 without running Mnemo | `tests/test_channels.py` |
| Duplicate callback | Returns duplicate acknowledgement and sends no second reply | `tests/test_channels.py` |
| Valid text message | Runs Mnemo and sends one Feishu rich post reply when streaming fallback is disabled | `tests/test_channels.py` |
| Markdown reply | Preserves Markdown as Feishu rich post content instead of plain text on the fallback path | `tests/test_channels.py` |
| Streaming reply | Creates a CardKit streaming card, replies with an interactive card, updates the content element, closes streaming mode, and updates the final footer | `tests/test_channels.py` |
| QR onboarding success | Starts registration, polls credentials, probes bot metadata, and saves masked status | `tests/test_channels.py` |
| Web onboarding API | Starts/polls a session and never returns app secret | `tests/test_web.py` |
| Missing app credentials | CLI exits with `mnemo:` error and no traceback | `tests/test_cli.py` |
| Package install | Installed wheel exposes `mnemo.channels.FeishuChannelConfig` and `build_feishu_server` | `tests/package_install_smoke.py` |

### 5. Good/Base/Bad Cases
- Good: keep Feishu parsing, QR registration, auth checks, and outbound API calls inside `mnemo/channels/feishu.py`.
- Good: use provider/runtime config resolution shared by the CLI, then call `run_provider()` or `run_local()`.
- Good: use Feishu official CardKit streaming APIs when `streaming=true` instead of simulating streaming by repeatedly editing rich-post messages.
- Base: webhook mode is enough for Cloudflare Tunnel or another HTTPS reverse proxy.
- Base: QR scan-to-create defaults to websocket because it avoids manual webhook callback setup.
- Bad: storing `FEISHU_APP_SECRET` in Web settings, browser storage, logs, or unmasked status payloads.
- Bad: running a provider call synchronously before acknowledging Feishu's webhook callback.
- Bad: using the rich-post edit loop when official streaming-card permissions are available.

### 6. Tests Required
- Channel tests for challenge, token/signature failure, dedup, background runtime processing, outbound send shape, and session continuity file.
- Channel/Web tests for QR onboarding, saved config status, and no secret leakage in status payloads.
- CLI tests for help text, status output, and missing credential errors.
- Install script syntax checks and package smoke import coverage.

## Scenario: Install Onboard And Web Service

### 1. Scope / Trigger
- Trigger: changes to `scripts/install.sh`, `mnemo onboard`, `mnemo service ...`, `mnemo/runtime/service.py`, or runtime API credential setup.
- Goal: fresh installs should be able to configure API access, optionally bind Feishu/Lark, and start the local web service without manual follow-up commands.

### 2. Signatures
- `mnemo onboard [--state-dir DIR] [--workspace-root DIR] [--provider local|openai-compatible|anthropic] [--base-url URL] [--model MODEL] [--api-key-env ENV] [--api-key KEY] [--bind-feishu|--skip-feishu] [--start-service|--no-start-service] [--service-mode auto|launchd|systemd|detached] [--non-interactive] [--json]`
- `mnemo service install|start|restart [--state-dir DIR] [--host HOST] [--port PORT] [--mode auto|launchd|systemd|detached] [--dry-run] [--json]`
- `mnemo service stop|status [--state-dir DIR] [--json]`
- `mnemo.runtime.service.save_service_env(state_dir, values) -> dict[str, Any]`
- `mnemo.runtime.service.service_status(state_dir) -> dict[str, Any]`

### 3. Contracts
- `mnemo onboard` initializes the state directory, writes non-secret runtime settings through `save_user_settings()`, and never stores raw API keys in `settings.json`.
- A pasted or copied provider key may be written only to `<state_dir>/service/mnemo-web.env` with mode `0600`; CLI JSON/status output exposes only env var names.
- The background service launches `python -m mnemo web ...` so the installed venv owns imports and the Web settings overlay remains the source of runtime provider configuration.
- Web UI password protection resolves from `MNEMO_WEB_PASSWORD` or `MNEMO_WEB_PASSWORD_SHA256`; `/api/health` remains unauthenticated for service checks, while the app shell and non-auth API routes require a signed session cookie.
- Service launchers resolve state and workspace paths to absolute paths before writing launchd/systemd/detached metadata.
- When `<state_dir>/channels/feishu_config.json` contains saved credentials with `connection=websocket`, the service launcher also starts `python -m mnemo channels feishu serve --connection websocket ...` as a child sidecar.
- Feishu sidecar provider flags are derived from non-secret runtime settings; raw app secrets remain in `channels/feishu_config.json` and provider keys remain in the service env file.
- Feishu sidecar logs are separate: `<state_dir>/logs/mnemo-feishu.log` and `<state_dir>/logs/mnemo-feishu.error.log`.
- The service supervisor exits if either web or Feishu sidecar exits; launchd/systemd/detached restart policy may then relaunch the whole service.
- Service manager selection is `launchd` on macOS, `systemd --user` on Linux, and detached process fallback when no supported manager is available or an explicit mode is requested.
- `--dry-run` writes service files for inspection but must not call `launchctl`, `systemctl`, or spawn a detached process.
- The install script runs `mnemo onboard` by default; non-interactive installs pass `--non-interactive --skip-feishu` to avoid blocking on QR or prompts.
- Interactive onboard may call the existing Feishu QR flow; non-interactive Feishu binding requires explicit `--bind-feishu`.
- Acknowledgements for Hermes Agent and OpenClaw must remain in notices/comments when implementation references their install, gateway, or onboarding patterns.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Non-interactive provider onboard | Settings are saved, service env has only named secret variables, stdout is secret-free | `tests/test_cli.py` |
| Web password auth | Unauthenticated app/API requests are gated, login sets an HttpOnly session cookie, and secrets stay out of responses | `tests/test_web.py` |
| Service dry-run install | Launcher/meta files are written, status is compact, and no process is started | `tests/test_cli.py` |
| Feishu websocket config | Service dry-run launcher includes a Feishu sidecar and no app/API secrets | `tests/test_cli.py` |
| Feishu webhook config | Service dry-run launcher skips the websocket sidecar | `tests/test_cli.py` |
| Install script syntax/docs | `bash -n` passes and the script references onboard plus Feishu fallback commands | `tests/test_channels.py` |
| Package install | Installed wheel exposes service helpers and CLI entrypoints | `tests/package_install_smoke.py` |

### 5. Good/Base/Bad Cases
- Good: use `mnemo onboard --non-interactive --provider openai-compatible --base-url ... --model ... --api-key-env MNEMO_API_KEY --api-key ...` for unattended setup.
- Good: keep service process-manager code in `mnemo/runtime/service.py` with CLI as a thin wrapper.
- Good: let QR-bound Feishu websocket bots ride the normal Mnemo service lifecycle instead of requiring a second manual terminal.
- Base: detached mode is acceptable where launchd/systemd are unavailable.
- Bad: asking users to run `mnemo web` manually after the default installer completes.
- Bad: QR onboarding that reports success but leaves no process consuming Feishu websocket events.
- Bad: putting provider secrets in Web settings, installer logs, CLI JSON, launchd plist, or systemd unit files.

### 6. Tests Required
- CLI tests for onboard help, non-interactive runtime setup, service env permissions, service dry-run install, and service status.
- CLI tests for Feishu sidecar inclusion/exclusion and secret-free launcher/status output.
- Install script syntax checks.
- Package smoke coverage for the service helper module.
