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
- `SkillService.crystallize_from_run(run_id: str, name: str, *, description: str | None = None, notes: str | None = None) -> dict[str, Any]`
- `SkillService.patch_candidate(source_name: str, name: str, replacements: Any, *, description: str | None = None, replace_all: Any = False) -> dict[str, Any]`
- `SkillService.run_eval_case(case_id: str) -> dict[str, Any]`
- `SkillService.review(name: str) -> dict[str, Any]`
- `default_skill_roots(state_dir: str | Path, workspace: str | Path | None = None, home: str | Path | None = None) -> list[Path]`
- Tool: `skill_record_outcome(name: str, outcome: success|failure|neutral, score?: -1..1, evidence?: object[])`
- Tool: `skill_crystallize_from_run(run_id: str, name: str, description?: str, notes?: str)`
- Tool: `skill_patch_candidate(source_name: str, name: str, replacements: [{old: str, new: str}], description?: str, replace_all?: bool)`
- Tool: `skill_run_eval_case(case_id: str)`
- Tool: `skill_review_candidate(name: str)`
- CLI: `mnemo skills usage [name] [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo evals create <run_id> <name> --case-json OBJECT [--state-dir DIR] [--json]`
- CLI: `mnemo evals list [--status STATUS] [--skill-name NAME] [--state-dir DIR] [--json]`
- CLI: `mnemo evals record <case_id> passed|failed [--result-json OBJECT] [--state-dir DIR] [--json]`

### 3. Contracts
- `skill_view` records a `viewed` event only after the skill exists.
- `skill_record_outcome` records an `outcome` event and does not mutate the skill body.
- Scores must remain in `[-1, 1]`.
- Context cards may include compact `usage` stats, never full skill bodies.
- Ranking may use usage stats, but ordering must remain deterministic.
- Default skill roots include Mnemo state skills, workspace `.mnemo/skills`, workspace `.agents/skills`, workspace `.claude/skills`, workspace `.hermes/skills`, workspace `.openclaw/skills`, and home `.claude/.hermes/.openclaw` skills.
- Default skill roots must be de-duplicated while preserving first-seen order.
- Explicit `skills scan --root` paths are additive to default roots.
- Evidence is stored as JSON and returned only through explicit usage inspection APIs, not prompt cards.
- `mnemo skills usage` is read-only and returns usage events plus aggregate stats from `StateStore`.
- `skill_crystallize_from_run` is model-directed: the model decides when to call it and supplies the name/description.
- After-turn learning reflection can call `skill_propose_candidate` from the same compact packet used for memory/tool/eval candidates.
- Crystallization reads completed run events and stores a `draft` skill with `source="run:<run_id>:crystallized"`.
- Crystallized skill bodies may include compact tool names, summaries, evidence counts, and source run id.
- Crystallized skill bodies must not include raw user messages, full tool results, or raw payload bodies.
- Runs without a completed event or without successful tool results are rejected.
- `skill_patch_candidate` is model-directed and applies exact in-memory replacements to an existing skill body.
- Skill patch candidates are stored as `draft` with `source="skill:<source_name>:patch"`.
- Skill patching rejects missing source skills, empty replacements, missing replacement text, ambiguous replacement text unless `replace_all=true`, no-op patches, and patch candidate names that would overwrite an active skill.
- Skill patching never mutates the source skill and never writes `SKILL.md`.
- `skill_review_candidate` updates a generated skill candidate to `ready` or `blocked:*`.
- Review validates name, description, body, and negative usage evidence.
- Skill eval cases target skills through `case.skill_name`, `case.skill_candidate`, `case.skill`, or `case.name`.
- The shared `mnemo evals` CLI can create/list skill-targeted cases and record external eval outcomes; it does not run deterministic skill assertions by itself.
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
| Successful run crystallization | Store a draft skill sourced from the run | `tests/test_skills_filesystem.py` |
| Incomplete or empty run crystallization | Reject without creating a skill | `tests/test_skills_filesystem.py` |
| Crystallized body payload safety | Include compact summaries and omit raw tool payloads | `tests/test_skills_filesystem.py` |
| Skill patch success | Create a draft patched candidate without mutating source skill | `tests/test_skills_filesystem.py` |
| Skill patch ambiguity | Reject duplicate old text unless `replace_all=true` | `tests/test_skills_filesystem.py` |
| Skill patch tool | Return compact summary/evidence without body | `tests/test_tools.py` |
| After-turn skill candidate | Mixed learning reflection can create a draft skill and project a learning chip | `tests/test_runtime.py` |
| Skill eval pass | Persist eval case `passed` with assertion results | `tests/test_skills_filesystem.py` |
| Skill eval failure | Persist eval case `failed` with errors | `tests/test_skills_filesystem.py` |
| Linked eval missing pass | Review marks skill `blocked:missing_eval` | `tests/test_skills_filesystem.py` |
| Linked failed eval | Review marks skill `blocked:failed_eval` | `tests/test_skills_filesystem.py` |
| Review tool | Return compact summary/evidence without body | `tests/test_tools.py` |
| Crystallization tool | Return compact summary/evidence without body or raw payloads | `tests/test_tools.py` |
| Eval tool | Return compact summary/evidence without body | `tests/test_tools.py` |
| Shared eval CLI | Create/list skill-targeted eval cases and record external outcomes | `tests/test_cli.py` |
| Skill usage CLI | Return usage events and aggregate stats without mutating skill state | `tests/test_cli.py` |
| Skill cards | Include compact usage stats and omit body | `tests/test_skills_filesystem.py` |
| Default roots | Include mainstream client roots and de-duplicate | `tests/test_skills_filesystem.py` |
| CLI scan defaults | Import workspace mainstream roots without explicit `--root` | `tests/test_cli.py` |
| Storage stats | Count uses/views/outcomes and average scored events | `tests/test_storage.py` |
| Harness regression | Built-in `skill-evolution` suite covers crystallization, eval gates, and compact cards | `tests/test_harness.py`, `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: model calls `skill_record_outcome` after observing whether a skill helped.
- Good: model calls `skill_crystallize_from_run` after a repeated or high-value successful run, then proposes evals before promotion.
- Good: model calls `skill_patch_candidate` to create a bounded draft revision from a useful existing skill, then evaluates and reviews it.
- Good: model proposes an eval case, calls `skill_run_eval_case`, then reviews the candidate.
- Good: model calls `skill_review_candidate` before requesting explicit promotion.
- Good: reuse `default_skill_roots()` for runtime and CLI scanning so prompt cards and `skills scan` see the same client roots.
- Base: skill ranking uses `avg_score`, success count, use count, then name.
- Bad: automatically rewriting a skill body from one successful run.
- Bad: mutating an active source skill directly from a patch proposal.
- Bad: promoting a generated skill without review when review evidence is available.
- Bad: hiding large evidence payloads inside prompt skill cards.

### 6. Tests Required
- Storage round-trip for usage events and aggregate stats.
- Tool harness test for `skill_view` and `skill_record_outcome`.
- Tool harness test for `skill_crystallize_from_run`.
- Tool harness test for `skill_patch_candidate`.
- Tool harness test for `skill_run_eval_case`.
- Tool harness test for `skill_review_candidate`.
- CLI test for skill usage event and stats inspection.
- CLI test for shared eval case creation, listing, and result recording.
- Skill service test for usage stats and deterministic ranking.
- Skill service test for default root ordering and de-duplication.
- CLI test for scanning a workspace mainstream root without `--root`.
- Skill service tests for crystallized draft body shape and rejection paths.
- Skill service tests for patch candidate success, source immutability, missing source, and ambiguity handling.
- Skill service tests for running linked eval cases and review gating.
- Skill service tests for ready and blocked review states.
- Harness suite `skill-evolution`: assert crystallization omits raw payloads, eval pass enables review, failed or missing evals block review, and context cards omit bodies.

### 7. Wrong vs Correct
#### Wrong
```python
skill["body"] += "\nThis worked once, always do it."
```

#### Correct
```python
store.record_skill_usage(run_id, "writer", "outcome", outcome="success", score=0.8)
```
