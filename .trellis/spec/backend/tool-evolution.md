# Tool Evolution Contracts

## Scenario: Generated Tool Candidate Eval Gate

### 1. Scope / Trigger
- Trigger: changes to `tool_candidates`, `eval_cases`, `mnemo/tools/evolution.py`, or lifecycle-related tool handlers.
- Goal: keep generated tools inactive until their candidate spec is valid and at least one linked eval case has passed.

### 2. Signatures
- `StateStore.get_tool_candidate(candidate_id: str) -> dict[str, Any] | None`
- `StateStore.list_tool_candidates(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.update_tool_candidate_status(candidate_id: str, status: str) -> None`
- `StateStore.upsert_generated_tool(*, candidate_id: str, name: str, description: str, risk: str, input_schema: dict[str, Any], implementation: dict[str, Any], status: str = "active") -> str`
- `StateStore.get_generated_tool(name: str) -> dict[str, Any] | None`
- `StateStore.list_generated_tools(status: str | None = "active", limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.update_generated_tool_status(name: str, status: str) -> None`
- `StateStore.get_eval_case(case_id: str) -> dict[str, Any] | None`
- `StateStore.list_eval_cases(status: str | None = None, *, tool_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.list_eval_cases(status: str | None = None, *, tool_name: str | None = None, skill_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.update_eval_case_status(case_id: str, status: str, *, result: dict[str, Any] | None = None) -> None`
- `ToolEvolutionService.review_candidate(candidate_id: str) -> dict[str, Any]`
- `ToolEvolutionService.install_candidate(candidate_id: str, *, available_tools: Mapping[str, Any]) -> dict[str, Any]`
- `ToolEvolutionService.uninstall_generated_tool(name: str) -> dict[str, Any]`
- Tool: `eval_record_result(case_id: str, status: passed|failed, result?: object)`
- Tool: `tool_review_candidate(candidate_id: str)`
- Tool: `tool_install_candidate(candidate_id: str)`
- Tool: `tool_uninstall_generated(name: str)`

### 3. Contracts
- `tool_propose_candidate` creates `draft` candidates only.
- Candidate review never activates executable generated code.
- Valid candidate specs require matching `name`, non-empty `description`, valid `risk`, and object `input_schema`.
- Linked eval cases target a candidate through `case.tool_candidate`, `case.tool_name`, or `case.name`.
- The same eval table may target skills through `case.skill_name`, `case.skill_candidate`, `case.skill`, or `case.name`.
- A candidate with invalid spec becomes `blocked:invalid_spec`.
- A valid candidate without passed linked evals becomes `blocked:missing_eval`.
- A valid candidate with at least one passed linked eval becomes `ready`.
- `ready` means installable only after implementation validation; it is not active by itself.
- Installed generated tools are durable rows in `generated_tools` with `status="active"`.
- The first supported generated tool implementation is an `alias` to an existing registered tool.
- Alias implementations use `implementation.target_tool` and optional `implementation.argument_map`.
- `argument_map` maps target arguments from source arguments, constants, or defaults.
- Install rejects unknown targets, self-aliasing, malformed implementations, and permission downgrades.
- Install rejects generated tool names that collide with existing registered tools.
- Generated tool risk must be equal to or higher than the target tool risk.
- Uninstall sets the generated tool `status` to `disabled` and returns the candidate to `ready`.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Missing candidate | `NotFoundError`; tool harness returns compact failed result | `tests/test_tool_evolution.py`, `tests/test_tools.py` |
| Invalid spec | `blocked:invalid_spec` and errors returned | `tests/test_tool_evolution.py` |
| Valid spec, no passed eval | `blocked:missing_eval` | `tests/test_tool_evolution.py` |
| Valid spec, passed linked eval | `ready` | `tests/test_tool_evolution.py` |
| Eval result recorded | Eval case status/result persists | `tests/test_tools.py`, `tests/test_storage.py` |
| Ready alias candidate installed | Generated tool row becomes `active`, candidate becomes `installed` | `tests/test_tool_evolution.py`, `tests/test_tools.py` |
| Install before ready | Candidate becomes `blocked:not_ready`, no generated tool row | `tests/test_tool_evolution.py` |
| Unknown alias target | Candidate becomes `blocked:install_invalid` | `tests/test_tool_evolution.py` |
| Risk downgrade | Candidate becomes `blocked:install_invalid` | `tests/test_tool_evolution.py` |
| Existing tool name collision | Candidate becomes `blocked:install_invalid` | `tests/test_tool_evolution.py` |
| Uninstall generated tool | Tool row becomes `disabled`, registry drops spec | `tests/test_tools.py` |

### 5. Good/Base/Bad Cases
- Good: model proposes candidate, proposes eval case, records eval result, then reviews candidate.
- Good: model installs a ready alias candidate only after eval has passed.
- Base: `ready` means reviewed and installable, not active.
- Bad: registering generated code directly from `tool_propose_candidate`.
- Bad: marking a candidate ready without any passed linked eval.
- Bad: aliasing an admin tool with a read-risk generated spec.

### 6. Tests Required
- Storage round-trip for tool candidates and eval cases.
- Service tests for invalid, missing-eval, and ready outcomes.
- Tool harness test for model-facing lifecycle tools.
- Storage round-trip for installed generated tools.
- Runtime test that active generated tools appear in provider tool specs.
- Tool harness tests for install, execution, compact evidence, and uninstall.

### 7. Wrong vs Correct
#### Wrong
```python
registry.register(generated_spec, generated_handler)
```

#### Correct
```python
store.update_tool_candidate_status(candidate_id, "ready")
```

#### Wrong
```python
spec = {"risk": "read", "implementation": {"type": "alias", "target_tool": "file_write"}}
```

#### Correct
```python
spec = {"risk": "admin", "implementation": {"type": "alias", "target_tool": "file_write"}}
```
