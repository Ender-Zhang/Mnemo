# Skill Evolution Contracts

## Scenario: Skill Usage And Outcome Signals

### 1. Scope / Trigger
- Trigger: changes to `mnemo/skills/service.py`, skill-related tool handlers, skill storage APIs, or prompt skill cards.
- Goal: let the model record skill outcomes without adding a fixed workflow router.

### 2. Signatures
- `StateStore.record_skill_usage(run_id: str, skill_name: str, event_type: str, *, outcome=None, score=None, evidence=None) -> str`
- `StateStore.list_skill_usage(skill_name: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.skill_usage_stats() -> dict[str, dict[str, Any]]`
- `SkillService.context_cards(limit: int = 12) -> list[dict[str, Any]]`
- Tool: `skill_record_outcome(name: str, outcome: success|failure|neutral, score?: -1..1, evidence?: object[])`

### 3. Contracts
- `skill_view` records a `viewed` event only after the skill exists.
- `skill_record_outcome` records an `outcome` event and does not mutate the skill body.
- Scores must remain in `[-1, 1]`.
- Context cards may include compact `usage` stats, never full skill bodies.
- Ranking may use usage stats, but ordering must remain deterministic.
- Evidence is stored as JSON and returned only through explicit usage inspection APIs, not prompt cards.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| `skill_view` missing skill | Return `NotFoundError`; no usage event | `tests/test_tools.py` |
| `skill_view` existing skill | Record `viewed` event | `tests/test_tools.py` |
| Outcome score omitted | Default by outcome: success=1, failure=-1, neutral=0 | `tests/test_tools.py` |
| Outcome score out of range | Tool failure | `tests/test_tools.py` |
| Skill cards | Include compact usage stats and omit body | `tests/test_skills_filesystem.py` |
| Storage stats | Count uses/views/outcomes and average scored events | `tests/test_storage.py` |

### 5. Good/Base/Bad Cases
- Good: model calls `skill_record_outcome` after observing whether a skill helped.
- Base: skill ranking uses `avg_score`, success count, use count, then name.
- Bad: automatically rewriting a skill body from one successful run.
- Bad: hiding large evidence payloads inside prompt skill cards.

### 6. Tests Required
- Storage round-trip for usage events and aggregate stats.
- Tool harness test for `skill_view` and `skill_record_outcome`.
- Skill service test for usage stats and deterministic ranking.

### 7. Wrong vs Correct
#### Wrong
```python
skill["body"] += "\nThis worked once, always do it."
```

#### Correct
```python
store.record_skill_usage(run_id, "writer", "outcome", outcome="success", score=0.8)
```
