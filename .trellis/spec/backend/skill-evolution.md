# Skill Evolution Contracts

## Scenario: Skill Usage And Outcome Signals

### 1. Scope / Trigger
- Trigger: changes to `mnemo/skills/service.py`, skill-related tool handlers, skill storage APIs, or prompt skill cards.
- Goal: let the model record skill outcomes without adding a fixed workflow router.

### 2. Signatures
- `StateStore.record_skill_usage(run_id: str, skill_name: str, event_type: str, *, outcome=None, score=None, evidence=None) -> str`
- `StateStore.list_skill_usage(skill_name: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.skill_usage_stats() -> dict[str, dict[str, Any]]`
- `StateStore.list_eval_cases(status: str | None = None, *, tool_name: str | None = None, skill_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `SkillService.context_cards(limit: int = 12) -> list[dict[str, Any]]`
- `SkillService.run_eval_case(case_id: str) -> dict[str, Any]`
- `SkillService.review(name: str) -> dict[str, Any]`
- Tool: `skill_record_outcome(name: str, outcome: success|failure|neutral, score?: -1..1, evidence?: object[])`
- Tool: `skill_run_eval_case(case_id: str)`
- Tool: `skill_review_candidate(name: str)`

### 3. Contracts
- `skill_view` records a `viewed` event only after the skill exists.
- `skill_record_outcome` records an `outcome` event and does not mutate the skill body.
- Scores must remain in `[-1, 1]`.
- Context cards may include compact `usage` stats, never full skill bodies.
- Ranking may use usage stats, but ordering must remain deterministic.
- Evidence is stored as JSON and returned only through explicit usage inspection APIs, not prompt cards.
- `skill_review_candidate` updates a generated skill candidate to `ready` or `blocked:*`.
- Review validates name, description, body, and negative usage evidence.
- Skill eval cases target skills through `case.skill_name`, `case.skill_candidate`, `case.skill`, or `case.name`.
- `skill_run_eval_case` evaluates deterministic structured assertions against skill body/description and records `passed` or `failed`.
- Supported skill eval assertions: `body_contains`, `description_contains`, `body_not_contains`, `body_forbids`, and `min_body_chars`.
- Review blocks linked failed evals as `blocked:failed_eval`.
- Review blocks linked pending evals with no passed eval as `blocked:missing_eval`.
- Review never auto-promotes or writes `SKILL.md`.
- Promotion remains explicit through `SkillService.promote`.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| `skill_view` missing skill | Return `NotFoundError`; no usage event | `tests/test_tools.py` |
| `skill_view` existing skill | Record `viewed` event | `tests/test_tools.py` |
| Outcome score omitted | Default by outcome: success=1, failure=-1, neutral=0 | `tests/test_tools.py` |
| Outcome score out of range | Tool failure | `tests/test_tools.py` |
| Valid draft review | Mark skill `ready` | `tests/test_skills_filesystem.py` |
| Invalid draft review | Mark skill `blocked:*` with errors | `tests/test_skills_filesystem.py` |
| Negative usage review | Mark skill `blocked:negative_usage` | `tests/test_skills_filesystem.py` |
| Skill eval pass | Persist eval case `passed` with assertion results | `tests/test_skills_filesystem.py` |
| Skill eval failure | Persist eval case `failed` with errors | `tests/test_skills_filesystem.py` |
| Linked eval missing pass | Review marks skill `blocked:missing_eval` | `tests/test_skills_filesystem.py` |
| Linked failed eval | Review marks skill `blocked:failed_eval` | `tests/test_skills_filesystem.py` |
| Review tool | Return compact summary/evidence without body | `tests/test_tools.py` |
| Eval tool | Return compact summary/evidence without body | `tests/test_tools.py` |
| Skill cards | Include compact usage stats and omit body | `tests/test_skills_filesystem.py` |
| Storage stats | Count uses/views/outcomes and average scored events | `tests/test_storage.py` |

### 5. Good/Base/Bad Cases
- Good: model calls `skill_record_outcome` after observing whether a skill helped.
- Good: model proposes an eval case, calls `skill_run_eval_case`, then reviews the candidate.
- Good: model calls `skill_review_candidate` before requesting explicit promotion.
- Base: skill ranking uses `avg_score`, success count, use count, then name.
- Bad: automatically rewriting a skill body from one successful run.
- Bad: promoting a generated skill without review when review evidence is available.
- Bad: hiding large evidence payloads inside prompt skill cards.

### 6. Tests Required
- Storage round-trip for usage events and aggregate stats.
- Tool harness test for `skill_view` and `skill_record_outcome`.
- Tool harness test for `skill_run_eval_case`.
- Tool harness test for `skill_review_candidate`.
- Skill service test for usage stats and deterministic ranking.
- Skill service tests for running linked eval cases and review gating.
- Skill service tests for ready and blocked review states.

### 7. Wrong vs Correct
#### Wrong
```python
skill["body"] += "\nThis worked once, always do it."
```

#### Correct
```python
store.record_skill_usage(run_id, "writer", "outcome", outcome="success", score=0.8)
```
