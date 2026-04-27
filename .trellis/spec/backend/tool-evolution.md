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
- `ToolEvolutionService.rollback_generated_tool(name: str, *, reason: str = "") -> dict[str, Any]`
- Tool: `eval_record_result(case_id: str, status: passed|failed, result?: object)`
- Tool: `tool_review_candidate(candidate_id: str)`
- Tool: `tool_install_candidate(candidate_id: str)`
- Tool: `tool_uninstall_generated(name: str)`
- Tool: `tool_rollback_generated(name: str, reason?: str)`
- CLI: `mnemo tools candidates [--status STATUS] [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo tools review <candidate_id> [--state-dir DIR] [--json]`
- CLI: `mnemo tools install <candidate_id> [--state-dir DIR] [--json]`
- CLI: `mnemo tools uninstall <name> [--state-dir DIR] [--json]`
- CLI: `mnemo tools rollback <name> [--reason REASON] [--state-dir DIR] [--json]`
- CLI: `mnemo evals create <run_id> <name> --case-json OBJECT [--state-dir DIR] [--json]`
- CLI: `mnemo evals list [--status STATUS] [--tool-name NAME] [--skill-name NAME] [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo evals record <case_id> passed|failed [--result-json OBJECT] [--state-dir DIR] [--json]`

### 3. Contracts
- `tool_propose_candidate` creates `draft` candidates only.
- After-turn learning reflection can call `tool_propose_candidate` and `eval_propose_case` from the same compact packet used for memory/skill candidates.
- The CLI lifecycle commands are thin wrappers around `ToolEvolutionService`; validation logic stays in the service.
- `mnemo tools` and `mnemo tools list` both list currently available provider-facing tool specs.
- `mnemo tools candidates` reads candidates without changing candidate state.
- `mnemo evals create` validates the source run exists, parses `--case-json` as an object, and stores a draft eval case.
- `mnemo evals list` reads stored eval cases without changing eval or candidate state.
- `mnemo evals record` persists eval status/result through `StateStore.update_eval_case_status` after verifying the case exists.
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
- Rollback sets the generated tool `status` to `rolled_back`, marks the source candidate `rolled_back`, drops the active registry entry, and requires `review_candidate()` before reinstall.
- Rollback returns compact action, previous status, candidate status, and bounded reason without implementation payloads.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Missing candidate | `NotFoundError`; tool harness returns compact failed result | `tests/test_tool_evolution.py`, `tests/test_tools.py` |
| Invalid spec | `blocked:invalid_spec` and errors returned | `tests/test_tool_evolution.py` |
| Valid spec, no passed eval | `blocked:missing_eval` | `tests/test_tool_evolution.py` |
| Valid spec, passed linked eval | `ready` | `tests/test_tool_evolution.py` |
| Eval result recorded | Eval case status/result persists | `tests/test_tools.py`, `tests/test_storage.py` |
| After-turn tool/eval candidates | Mixed learning reflection can create draft tool and eval candidates from one packet | `tests/test_runtime.py` |
| Ready alias candidate installed | Generated tool row becomes `active`, candidate becomes `installed` | `tests/test_tool_evolution.py`, `tests/test_tools.py` |
| Install before ready | Candidate becomes `blocked:not_ready`, no generated tool row | `tests/test_tool_evolution.py` |
| Unknown alias target | Candidate becomes `blocked:install_invalid` | `tests/test_tool_evolution.py` |
| Risk downgrade | Candidate becomes `blocked:install_invalid` | `tests/test_tool_evolution.py` |
| Existing tool name collision | Candidate becomes `blocked:install_invalid` | `tests/test_tool_evolution.py` |
| Uninstall generated tool | Tool row becomes `disabled`, registry drops spec | `tests/test_tools.py` |
| Rollback generated tool | Tool row and candidate become `rolled_back`, registry drops spec, and direct reinstall is blocked until review | `tests/test_tool_evolution.py`, `tests/test_tools.py` |
| CLI candidate lifecycle | Review/install/uninstall commands update service state and keep `mnemo tools` list behavior | `tests/test_cli.py` |
| CLI rollback lifecycle | Rollback command returns compact status and hides the generated tool from available tool specs | `tests/test_cli.py` |
| CLI eval case lifecycle | Create/list/record persist case payload, target filters, and result status | `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: model proposes candidate, proposes eval case, records eval result, then reviews candidate.
- Good: model installs a ready alias candidate only after eval has passed.
- Base: `ready` means reviewed and installable, not active.
- Base: `rollback` is a safety lifecycle state; it does not delete candidate or generated tool history.
- Bad: registering generated code directly from `tool_propose_candidate`.
- Bad: marking a candidate ready without any passed linked eval.
- Bad: aliasing an admin tool with a read-risk generated spec.
- Bad: treating rollback as ordinary uninstall that leaves the candidate immediately installable.

### 6. Tests Required
- Storage round-trip for tool candidates and eval cases.
- Service tests for invalid, missing-eval, and ready outcomes.
- Tool harness test for model-facing lifecycle tools.
- CLI lifecycle test for candidate listing, review, install, uninstall, rollback, and missing-id errors.
- CLI eval case test for creating, listing by tool/skill target, and recording pass/fail results.
- Storage round-trip for installed generated tools.
- Runtime test that active generated tools appear in provider tool specs.
- Tool harness tests for install, execution, compact evidence, uninstall, and rollback.

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
