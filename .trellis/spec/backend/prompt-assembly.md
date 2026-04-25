# Prompt Assembly Contracts

## Scenario: Cache-Friendly Prompt Budgeting

### 1. Scope / Trigger
- Trigger: changes to `mnemo/prompt/assembly.py`, runtime prompt calls, prompt metadata, or provider message assembly.
- Goal: keep prompts stable for KV-cache reuse while limiting optional context growth.

### 2. Signatures
- `PromptAssembler.assemble(current_user_message: str, *, mission=None, checkpoint=None, tool_specs=None, memory_snapshot=None, memory_cards=None, skill_cards=None, token_budget=DEFAULT_PROMPT_TOKEN_BUDGET) -> AssembledPrompt`
- `AssembledPrompt.messages() -> list[dict[str, str]]`
- `AssembledPrompt.metadata() -> dict[str, Any]`

### 3. Contracts
- Stable prefix blocks must stay ordered before dynamic blocks.
- Non-droppable blocks: `system.identity`, `developer.operating_principles`, `mission.continuation`, `turn.current_user_message`.
- Droppable blocks: optional tool cards, L1 memory snapshot, memory index, and skill index.
- `memory.l1_snapshot` is daily-cache context and must appear before turn-scoped `memory.index`.
- `memory.l1_snapshot` is a compact index, not a replacement for `memory_search` / `memory_read`.
- CLI inspection of the same compiled context is read-only: `mnemo memory snapshot`.
- Tool schemas still travel through provider-native tool definitions; dropping `tools.cards` must not remove actual tool availability.
- Prompt block budgeting only applies to prompt messages; provider-native tool schemas are tracked in `metadata().tool_schema` separately.
- `metadata().tool_schema` contains `count`, ordered `names`, `token_estimate`, and `budget_scope="provider_native"`; it must not contain raw schema payloads.
- `metadata().prompt_token_estimate` equals prompt-message block tokens and excludes tool schema estimates.
- `metadata().dropped_blocks` records block id, title, estimate, and reason.
- Large mission checkpoint values must be compacted before token estimates are computed.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| No budget (`token_budget=None`) | Keep all blocks | `tests/test_prompt.py` |
| Budget exceeded with optional context | Drop optional blocks by lowest value/highest priority | `tests/test_prompt.py` |
| Budget exceeded after all optional drops | Keep required blocks and set `budget_exceeded=true` | `tests/test_prompt.py` |
| Large checkpoint value | Compact inside mission continuation | `tests/test_prompt.py` |
| Metadata inspection | No prompt content or secrets in metadata | `tests/test_prompt.py` |
| L1 snapshot present | Add `memory.l1_snapshot` with `daily_context` cache segment before `memory.index` | `tests/test_prompt.py` |
| Empty L1 snapshot | Do not inject `memory.l1_snapshot` | `tests/test_prompt.py` |
| CLI snapshot inspection | Existing compiled snapshot is inspectable without full page bodies | `tests/test_cli.py` |
| Tight prompt budget with tools | May drop `tools.cards`; tool schema metadata remains present | `tests/test_prompt.py` |
| Prompt inspect metadata | Includes compact tool schema metadata without raw schemas | `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: expose compact memory/skill indexes and let the model call tools for details.
- Good: keep provider-native tool schemas out of prompt block budgeting and metadata payload bodies.
- Base: keep deterministic block ordering for cache reuse.
- Bad: append large raw trajectories into the stable prefix.
- Bad: remove provider-native tool schemas when dropping prompt tool cards.

### 6. Tests Required
- Block order and cache segment tests.
- Metadata shape tests that exclude raw content.
- Budget tests that assert required blocks remain and optional blocks are recorded as dropped.
- Tool schema budget separation tests that assert compact metadata remains when `tools.cards` is dropped.
- Runtime/provider tests that assert prompt metadata is persisted in `prompt.assembled`.
- Runtime/provider tests that assert daily L1 memory snapshot content reaches provider messages when present.

### 7. Wrong vs Correct
#### Wrong
```python
blocks.append(PromptBlock(id="history.raw", content=dumps(full_run_trace), can_drop=False, ...))
```

#### Correct
```python
blocks.append(PromptBlock(id="memory.index", content=compact_cards, can_drop=True, ...))
```
