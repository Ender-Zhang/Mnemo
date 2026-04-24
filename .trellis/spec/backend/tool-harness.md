# Tool Harness Contracts

## Scenario: Built-In Tool Surface

### 1. Scope / Trigger
- Trigger: any change to `mnemo/tools/registry.py`, `mnemo/tools/standard.py`, `mnemo/core/models.py` tool models, or provider/runtime tool-loop payloads.
- Goal: keep the tool surface model-driven, provider-native, compact, and policy-gated without introducing workflow routers.

### 2. Signatures
- `ToolRegistry.specs() -> list[ToolSpec]`
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
- `working_note.retention`: optional model decision, either `ephemeral` or `memory_candidate`.
- `working_note` with `retention="memory_candidate"` stores metadata for DreamCycle; it does not create a memory candidate synchronously.
- Skill crystallization is exposed as a normal provider-native tool call; the harness only validates policy, executes the handler, and returns compact summary/evidence.
- `compact_tool_result` for crystallization must not include the generated skill body or raw source run payloads.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Unknown tool name | Raise `ToolError` before handler execution | Registry unit test |
| Disallowed risk | Return `ToolResult(ok=False)`, persist `tool.denied`, do not call handler | `tests/test_tools.py` |
| Path outside workspace | Return failed tool result with boundary error | `tests/test_standard_tools.py` |
| Binary file read | Return failed tool result, no decoded payload | Standard tool test when added |
| Shell command timeout | Return failed tool result with timeout error | Standard tool test when added |
| Provider tool result feedback | Send `compact_tool_result`, not full raw payload | Runtime/provider tests |
| Working note memory retention | Persist note metadata and compact evidence only | `tests/test_tools.py` |
| Skill candidate review | Return compact review status/evidence without body | `tests/test_tools.py` |
| Skill crystallization | Return compact crystallization evidence without body/raw payloads | `tests/test_tools.py` |
| Skill eval case run | Return compact eval status/evidence without body | `tests/test_tools.py` |

### 5. Good/Base/Bad Cases
- Good: add a new tool by defining `ToolSpec`, registering a handler, and adding summary/evidence projection.
- Base: read-only tools should be usable by the default policy.
- Bad: adding a handler that performs side effects while declaring `risk="read"`.
- Bad: returning large raw payloads to the model instead of compact summaries and evidence cards.

### 6. Tests Required
- Tool policy denial: assert handler is not called and `tool.denied` is recorded.
- Tool success: assert `tool.called`, `tool.result`, `tool_calls` persistence, and compact result shape.
- Working note retention metadata: assert stored metadata and compact result remain small.
- Skill review: assert status is persisted and compact result omits full skill body.
- Skill crystallization: assert draft status is persisted and compact result omits raw source payload.
- Skill eval case: assert eval status is persisted and compact result omits full skill body.
- Local path tools: assert workspace scoping and traversal rejection.
- Provider runtime: assert tool specs are passed to the adapter and tool results are returned as `role="tool"` messages.

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
