# Integration Contracts

## Scenario: MnemoCore SDK And API Schema

### 1. Scope / Trigger
- Trigger: changes to `mnemo/sdk/`, integration schema payloads, public SDK methods, or CLI API schema commands.
- Goal: keep external integrations compact, language-neutral, and backed by existing runtime services instead of a parallel workflow.

### 2. Signatures
- `mnemo.sdk.MnemoClient(state_dir=DEFAULT_STATE_DIR, workspace_root=None)`
- `MnemoClient.context(intent="", *, agent_role="general", budget_tokens=4000, include_associations=True, prompt_mode="full") -> dict[str, Any]`
- `MnemoClient.recall(seed: str, *, depth=2, context="", limit=8) -> dict[str, Any]`
- `MnemoClient.run(message: str, *, conversation_id=None, mission_id=None, prompt_mode="full") -> dict[str, Any]`
- `MnemoClient.replay(run_id: str) -> dict[str, Any]`
- `MnemoClient.evaluate(suite="smoke") -> dict[str, Any]`
- `mnemo.sdk.mnemo_core_api_schema() -> dict[str, Any]`
- CLI: `mnemo api schema [--json]`

### 3. Contracts
- The SDK is a reference in-process binding; it must not introduce a second runtime loop.
- `context()` reuses `PromptAssembler`, `MemoryEngine`, `SkillService`, `ToolRegistry`, and ToolBundle metadata.
- `context()` returns prompt-ready `messages` plus `text`, compact metadata, tool bundle metadata, and compact memory/skill cards.
- `context()` must not expose raw provider-native tool schemas in metadata or tool bundle payloads.
- `context(prompt_mode="none")` is rejected because `none` is diagnostic-only.
- `recall()` reuses memory query planning and returns compact associative cards without raw evidence or full transcripts.
- `run()` executes through `run_local()` and returns run ids, response, compact `tool_summary`, and chat `event_summary`.
- `replay()` reuses `replay_summary()`.
- `evaluate()` reuses `EvalHarness`.
- `mnemo_core_api_schema()` returns a JSON-serializable language-neutral contract for `context`, `recall`, `run`, `replay`, and `evaluate`.
- `mnemo api schema --json` wraps the schema as `{ "api_schema": ... }`; text mode prints readable method summaries.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| SDK import from package | Installed wheel exposes `mnemo.sdk.MnemoClient` and schema | `tests/package_install_smoke.py` |
| Context request | Prompt-ready messages and compact metadata without raw schemas | `tests/test_sdk.py` |
| Recall request | Compact associative cards with query plan and no raw evidence | `tests/test_sdk.py` |
| Run request | Existing runtime creates run ledger and compact tool summary | `tests/test_sdk.py` |
| Replay/evaluate request | Existing harness services return compact reports | `tests/test_sdk.py` |
| CLI schema JSON | Returns `api_schema` with all core methods | `tests/test_cli.py` |
| CLI schema text | Prints readable method summaries | `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: add future MCP/HTTP adapters as thin transports over `MnemoClient` or the same service functions.
- Good: keep SDK return payloads compact enough for external agents to pass through context capsules.
- Base: the first SDK implementation is local and dependency-free.
- Bad: duplicating memory search, prompt assembly, run execution, or eval logic inside SDK methods.
- Bad: exposing raw tool schemas, full session transcripts, or full artifact bodies in SDK summaries.

### 6. Tests Required
- SDK context, recall, run/replay/evaluate, and schema shape tests.
- CLI schema command tests for JSON and readable output.
- Package install smoke import coverage for `mnemo.sdk`.
