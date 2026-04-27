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
- `MnemoClient.run(message: str, *, conversation_id=None, mission_id=None, prompt_mode="full") -> dict[str, Any]`
- `MnemoClient.replay(run_id: str) -> dict[str, Any]`
- `MnemoClient.evaluate(suite="smoke", *, variants: list[str] | tuple[str, ...] | None = None, release_gate: bool = False) -> dict[str, Any]`
- `mnemo.sdk.mnemo_core_api_schema() -> dict[str, Any]`
- CLI: `mnemo api schema [--json]`
- CLI: `mnemo api capsule TASK... [--runtime RUNTIME] [--agent-type TYPE] [--requested-page ID] [--allowed-page ID] [--state-dir DIR] [--json]`

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
- `run()` executes through `run_local()` and returns run ids, response, compact `tool_summary`, and chat `event_summary`.
- `replay()` reuses `replay_summary()`.
- `evaluate()` reuses `EvalHarness`; without variants it returns the normal suite report.
- `evaluate(..., variants=[...])` returns the harness variant report for `no_memory`, `skills_only`, and/or `full_mnemo`.
- `evaluate(release_gate=True)` returns the fixed core release gate report across personalization, memory-safety, skill-evolution, proactive-watch, and external-harness gates; it cannot be combined with `variants`.
- `mnemo_core_api_schema()` returns a JSON-serializable language-neutral contract for `context`, `recall`, `capsule`, `run`, `replay`, and `evaluate`.
- The `evaluate` API schema exposes an optional `variants` array with the public harness variant enum.
- The `evaluate` API schema exposes `release_gate` as an optional boolean.
- `mnemo api schema --json` wraps the schema as `{ "api_schema": ... }`; text mode prints readable method summaries.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| SDK import from package | Installed wheel exposes `mnemo.sdk.MnemoClient` and schema | `tests/package_install_smoke.py` |
| Context request | Prompt-ready messages and compact metadata without raw schemas | `tests/test_sdk.py` |
| Recall request | Compact associative cards with query plan and no raw evidence | `tests/test_sdk.py` |
| Capsule request | Compact external-runtime capsule with pointer-only blocked pages and no raw state | `tests/test_sdk.py` |
| Run request | Existing runtime creates run ledger and compact tool summary | `tests/test_sdk.py` |
| Replay/evaluate request | Existing harness services return compact suite, variant, and release-gate reports | `tests/test_sdk.py` |
| CLI schema JSON | Returns `api_schema` with all core methods | `tests/test_cli.py` |
| CLI schema text | Prints readable method summaries | `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: add future MCP/HTTP adapters as thin transports over `MnemoClient` or the same service functions.
- Good: keep SDK return payloads compact enough for external agents to pass through context capsules.
- Base: the first SDK implementation is local and dependency-free.
- Bad: duplicating memory search, prompt assembly, run execution, or eval logic inside SDK methods.
- Bad: exposing raw tool schemas, full session transcripts, or full artifact bodies in SDK summaries.

### 6. Tests Required
- SDK context, recall, capsule, run/replay/evaluate, variant-report, release-gate, and schema shape tests.
- CLI schema command tests for JSON and readable output.
- Package install smoke import coverage for `mnemo.sdk`.

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
- CLI: `mnemo mcp tools [--state-dir DIR] [--json]`
- CLI: `mnemo mcp call TOOL --arguments-json JSON [--state-dir DIR] [--json]`
- CLI: `mnemo mcp serve [--state-dir DIR] [--transport content-length|jsonl]`

### 3. Contracts
- MCP is a transport/tool facade; it must reuse SDK and domain services rather than defining workflow steps.
- Tool descriptors use MCP-style `inputSchema` and annotations, plus a compact `mnemo.risk` field.
- `mnemo_context`, `mnemo_capsule`, `mnemo_recall`, `mnemo_run`, `mnemo_replay`, and `mnemo_eval` route through `MnemoClient`.
- `mnemo_capsule` is read-only and returns the same minimal-disclosure `context_capsule` shape as the SDK.
- `mnemo_eval` accepts optional `variants`; when present it returns the same compact harness variant report as the SDK.
- `mnemo_eval` accepts `release_gate: true`; when present it returns the same compact release-gate report as the SDK.
- `mnemo_update` writes memory candidates and W0 working notes only; it must not mutate stable memory pages directly.
- `mnemo_search` returns compact memory cards and query-plan metadata without raw evidence blobs.
- `mnemo_skills` returns compact skill cards; full skill bodies remain behind existing skill-specific surfaces.
- `mnemo_tools` returns compact tool cards and ToolBundle metadata; it must not return raw provider input schemas by default.
- `mnemo_watch` and `mnemo_cron` create durable scheduled items through `ScheduleService`; due processing still runs through the normal daemon queue.
- `mnemo_watch_feedback` records compact Watch outcomes and applies an explicit model/user policy decision through `ScheduleService`.
- `mnemo_runtime_status` includes compact scheduled-item status.
- JSON-RPC support covers `initialize`, `tools/list`, and `tools/call` with structured error responses.
- `mnemo mcp serve` defaults to MCP stdio `Content-Length` framing; JSONL stdio remains an explicit debug transport.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Tool descriptors | Core tool names, `inputSchema`, and read/write annotations are present | `tests/test_mcp.py` |
| Compact reads | Context/capsule/search/recall/skills/tools do not expose raw evidence, full state, or raw input schemas | `tests/test_mcp.py` |
| Update writes | External facts become memory candidates and observations become W0 notes | `tests/test_mcp.py` |
| Watch/Cron calls | MCP calls create scheduled watch/cron items, record Watch feedback policy, and runtime status reports due count | `tests/test_mcp.py` |
| Runtime calls | Run/replay/eval/variant-eval/release-gate/status reuse existing services and compact results | `tests/test_mcp.py` |
| JSON-RPC | Initialize, list, call, unknown-method, JSONL serving, and Content-Length framing behave predictably | `tests/test_mcp.py` |
| CLI | `mnemo mcp tools`, `mnemo mcp call`, and both serve transports support JSON and normalized errors | `tests/test_cli.py` |
| Package install | Installed wheel exposes `mnemo.mcp.MnemoMcpServer` | `tests/package_install_smoke.py` |

### 5. Good/Base/Bad Cases
- Good: add new MCP tools as thin wrappers over SDK/domain services with compact outputs.
- Good: keep tool outputs model-actionable and small enough for external context capsules.
- Base: watch/cron tools register scheduled work; model-led execution happens when the daemon queue drains the due item, then the model may record feedback policy through `mnemo_watch_feedback`.
- Bad: adding provider-specific workflow routing inside the MCP server.
- Bad: returning full traces, full artifacts, raw provider schemas, or stable-memory mutations from generic update calls.

### 6. Tests Required
- Direct MCP server tests for descriptors, calls, capsule compactness, variant-eval, release-gate, scheduled watch/cron, and Watch feedback surfaces.
- JSON-RPC tests for success, Content-Length framing, JSONL debug serving, and structured errors.
- CLI tests for JSON output, serve transport selection, and error normalization.
- Package install smoke import coverage for `mnemo.mcp`.
