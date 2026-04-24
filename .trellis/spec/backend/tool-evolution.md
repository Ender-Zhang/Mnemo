# Tool Evolution Contracts

## Scenario: Generated Tool Candidate Eval Gate

### 1. Scope / Trigger
- Trigger: changes to `tool_candidates`, `eval_cases`, `mnemo/tools/evolution.py`, or lifecycle-related tool handlers.
- Goal: keep generated tools inactive until their candidate spec is valid and at least one linked eval case has passed.

### 2. Signatures
- `StateStore.get_tool_candidate(candidate_id: str) -> dict[str, Any] | None`
- `StateStore.list_tool_candidates(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.update_tool_candidate_status(candidate_id: str, status: str) -> None`
- `StateStore.get_eval_case(case_id: str) -> dict[str, Any] | None`
- `StateStore.list_eval_cases(status: str | None = None, *, tool_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.update_eval_case_status(case_id: str, status: str, *, result: dict[str, Any] | None = None) -> None`
- `ToolEvolutionService.review_candidate(candidate_id: str) -> dict[str, Any]`
- Tool: `eval_record_result(case_id: str, status: passed|failed, result?: object)`
- Tool: `tool_review_candidate(candidate_id: str)`

### 3. Contracts
- `tool_propose_candidate` creates `draft` candidates only.
- Candidate review never activates executable generated code.
- Valid candidate specs require matching `name`, non-empty `description`, valid `risk`, and object `input_schema`.
- Linked eval cases target a candidate through `case.tool_candidate`, `case.tool_name`, or `case.name`.
- A candidate with invalid spec becomes `blocked:invalid_spec`.
- A valid candidate without passed linked evals becomes `blocked:missing_eval`.
- A valid candidate with at least one passed linked eval becomes `ready`.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Missing candidate | `NotFoundError` | Tool/service test when added |
| Invalid spec | `blocked:invalid_spec` and errors returned | `tests/test_tool_evolution.py` |
| Valid spec, no passed eval | `blocked:missing_eval` | `tests/test_tool_evolution.py` |
| Valid spec, passed linked eval | `ready` | `tests/test_tool_evolution.py` |
| Eval result recorded | Eval case status/result persists | `tests/test_tools.py`, `tests/test_storage.py` |

### 5. Good/Base/Bad Cases
- Good: model proposes candidate, proposes eval case, records eval result, then reviews candidate.
- Base: `ready` means reviewable, not installed.
- Bad: registering generated code directly from `tool_propose_candidate`.
- Bad: marking a candidate ready without any passed linked eval.

### 6. Tests Required
- Storage round-trip for tool candidates and eval cases.
- Service tests for invalid, missing-eval, and ready outcomes.
- Tool harness test for model-facing lifecycle tools.

### 7. Wrong vs Correct
#### Wrong
```python
registry.register(generated_spec, generated_handler)
```

#### Correct
```python
store.update_tool_candidate_status(candidate_id, "ready")
```
