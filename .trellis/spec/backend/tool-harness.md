# Tool Harness Contracts

## Scenario: Built-In Tool Surface

### 1. Scope / Trigger
- Trigger: any change to `mnemo/tools/registry.py`, `mnemo/tools/standard.py`, `mnemo/core/models.py` tool models, or provider/runtime tool-loop payloads.
- Goal: keep the tool surface model-driven, provider-native, compact, and policy-gated without introducing workflow routers.

### 2. Signatures
- `ToolRegistry.specs() -> list[ToolSpec]`
- `ToolRegistry.from_store(store: StateStore) -> ToolRegistry`
- `ToolRegistry.load_generated_tools(generated_tools: Iterable[dict[str, Any]]) -> None`
- `ToolRegistry.execute(call: ToolCallEnvelope, context: ToolContext) -> ToolResult`
- `ToolHarness.execute(call: ToolCallEnvelope, *, run_id: str, mission_id: str) -> ToolResult`
- `ToolExecutionPolicy.check(spec: ToolSpec) -> ToolPermission`
- `tool_specs_as_json_schema(specs: list[ToolSpec]) -> list[dict[str, Any]]`
- `compact_tool_result(result: ToolResult) -> dict[str, Any]`

### 3. Contracts
- `ToolSpec.name`: unique provider-facing function name.
- `ToolSpec.risk`: one of `read`, `write`, `external`, `admin`.
- `ToolSpec.input_schema`: JSON-schema-compatible object with `additionalProperties: false`.
- `ToolCallEnvelope.arguments`: already parsed dict from the provider-native tool call.
- `ToolResult.result`: full persisted payload for ledger and replay.
- `ToolResult.summary` and `ToolResult.evidence`: compact model/UI payloads.
- `ToolContext.workspace_root`: resolved root for local file and shell tools.
- Provider-native tool schemas are sent through adapter requests, not embedded as raw prompt blocks or prompt metadata.
- `artifact_update` returns artifact id, title, and kind; artifact body remains in storage.
- `memory_search` may return `linked_page` matches from one-hop memory associations.
- `memory_read` reads either a memory candidate or a stable memory page by id.
- `file_patch(path, replacements, replace_all=False)` applies exact UTF-8 text replacements under `ToolContext.workspace_root` and is `admin` risk.
- `file_patch` rejects missing text, ambiguous text when `replace_all` is false, binary files, and paths outside the workspace.
- OpenAI-compatible adapters convert `tool_calls[].function` into `ToolCallEnvelope`.
- Anthropic adapters convert `tool_use` content blocks into `ToolCallEnvelope` and return tool results as `tool_result` content blocks.
- `working_note.retention`: optional model decision, either `ephemeral` or `memory_candidate`.
- `working_note` with `retention="memory_candidate"` stores metadata for DreamCycle; it does not create a memory candidate synchronously.
- Skill crystallization is exposed as a normal provider-native tool call; the harness only validates policy, executes the handler, and returns compact summary/evidence.
- `compact_tool_result` for crystallization must not include the generated skill body or raw source run payloads.
- `skill_patch_candidate` is exposed as a normal provider-native tool call and returns patch metadata, not the patched skill body.
- Active generated tools are loaded from `StateStore.list_generated_tools(status="active")`.
- Generated tools are normal provider-native tools once loaded into `ToolRegistry`.
- Generated tool aliases execute by mapping model arguments to an existing target tool handler.
- Compact results for install/uninstall and generated tool execution must not include implementation payloads.
- `artifact.card` events carry artifact metadata only; clients fetch body content explicitly when the user opens the artifact.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Unknown tool name | Raise `ToolError` before handler execution | Registry unit test |
| Disallowed risk | Return `ToolResult(ok=False)`, persist `tool.denied`, do not call handler | `tests/test_tools.py` |
| Path outside workspace | Return failed tool result with boundary error | `tests/test_standard_tools.py` |
| File patch exact edit | Admin policy applies exact replacement and returns compact patch evidence | `tests/test_standard_tools.py` |
| File patch ambiguity | Reject duplicate old text unless `replace_all=true` | `tests/test_standard_tools.py` |
| Binary file read | Return failed tool result, no decoded payload | Standard tool test when added |
| Shell command timeout | Return failed tool result with timeout error | Standard tool test when added |
| Provider tool result feedback | Send `compact_tool_result`, not full raw payload | Runtime/provider tests |
| Prompt metadata | Records compact tool schema count/names/estimate without raw schema payloads | `tests/test_prompt.py`, `tests/test_cli.py` |
| Anthropic tool use | Parse non-streaming and streaming `tool_use` blocks into `ToolCallEnvelope` | `tests/test_providers.py` |
| Anthropic tool result feedback | Convert Mnemo tool messages into Anthropic `tool_result` user blocks | `tests/test_providers.py` |
| Working note memory retention | Persist note metadata and compact evidence only | `tests/test_tools.py` |
| Skill candidate review | Return compact review status/evidence without body | `tests/test_tools.py` |
| Skill crystallization | Return compact crystallization evidence without body/raw payloads | `tests/test_tools.py` |
| Skill patch candidate | Return compact patch evidence without body and leave source skill unchanged | `tests/test_tools.py`, `tests/test_skills_filesystem.py` |
| Skill eval case run | Return compact eval status/evidence without body | `tests/test_tools.py` |
| Generated tool install | Return compact install evidence without implementation payload | `tests/test_tools.py` |
| Generated tool execution | Execute through existing handler and return generated-tool evidence | `tests/test_tools.py` |
| Generated tool runtime exposure | Provider runtime sends active generated tool specs | `tests/test_runtime.py` |
| Artifact card projection | Emit id/title/kind without full artifact body | `tests/test_web.py`, `mnemo/runtime/common.py` |
| Memory page read | Return stable page payload when `memory_read.id` is a memory page id | `tests/test_tools.py` |

### 5. Good/Base/Bad Cases
- Good: add a new tool by defining `ToolSpec`, registering a handler, and adding summary/evidence projection.
- Base: read-only tools should be usable by the default policy.
- Good: keep artifact bodies in storage and reference them by id in UI/event payloads.
- Good: expose associative memory through existing memory tools instead of a separate workflow router.
- Good: use `file_patch` for bounded edits instead of full-file overwrite when the old text is known.
- Bad: adding a handler that performs side effects while declaring `risk="read"`.
- Bad: returning large raw payloads to the model instead of compact summaries and evidence cards.

### 6. Tests Required
- Tool policy denial: assert handler is not called and `tool.denied` is recorded.
- Tool success: assert `tool.called`, `tool.result`, `tool_calls` persistence, and compact result shape.
- Working note retention metadata: assert stored metadata and compact result remain small.
- Skill review: assert status is persisted and compact result omits full skill body.
- Skill crystallization: assert draft status is persisted and compact result omits raw source payload.
- Skill patch: assert draft status is persisted and compact result omits full skill body.
- Skill eval case: assert eval status is persisted and compact result omits full skill body.
- Generated tool install: assert active tool row is persisted and compact result omits implementation payload.
- Generated tool execution: assert alias argument mapping reaches the target handler.
- Artifact update: assert card payload has id/title/kind and omits body content.
- Local path tools: assert workspace scoping and traversal rejection.
- File patch: assert admin gating, exact edit success, path traversal rejection, and ambiguous replacement handling.
- Provider runtime: assert tool specs are passed to the adapter and tool results are returned as `role="tool"` messages.
- Anthropic provider: assert tool specs are passed as `tools`, tool results become `tool_result` blocks, and streaming tool deltas are parsed.

### 7. Wrong vs Correct
#### Wrong
```python
ToolSpec(name="shell_exec", risk="write", input_schema={...})
```

#### Correct
```python
ToolSpec(name="shell_exec", risk="admin", input_schema={...})
```

#### Wrong
```python
subprocess.run(command, shell=True)
```

#### Correct
```python
subprocess.run(command, shell=False, capture_output=True, text=True)
```
