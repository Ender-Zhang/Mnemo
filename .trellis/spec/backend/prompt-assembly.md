# Prompt Assembly Contracts

## Scenario: Cache-Friendly Prompt Budgeting

### 1. Scope / Trigger
- Trigger: changes to `mnemo/prompt/assembly.py`, runtime prompt calls, prompt metadata, or provider message assembly.
- Goal: keep prompts stable for KV-cache reuse while limiting optional context growth.

### 2. Signatures
- `PromptAssembler.assemble(current_user_message: str, *, mission=None, checkpoint=None, tool_specs=None, memory_cards=None, skill_cards=None, token_budget=DEFAULT_PROMPT_TOKEN_BUDGET) -> AssembledPrompt`
- `AssembledPrompt.messages() -> list[dict[str, str]]`
- `AssembledPrompt.metadata() -> dict[str, Any]`

### 3. Contracts
- Stable prefix blocks must stay ordered before dynamic blocks.
- Non-droppable blocks: `system.identity`, `developer.operating_principles`, `mission.continuation`, `turn.current_user_message`.
- Droppable blocks: optional tool cards, memory index, and skill index.
- Tool schemas still travel through provider-native tool definitions; dropping `tools.cards` must not remove actual tool availability.
- `metadata().dropped_blocks` records block id, title, estimate, and reason.
- Large mission checkpoint values must be compacted before token estimates are computed.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| No budget (`token_budget=None`) | Keep all blocks | `tests/test_prompt.py` |
| Budget exceeded with optional context | Drop optional blocks by lowest value/highest priority | `tests/test_prompt.py` |
| Budget exceeded after all optional drops | Keep required blocks and set `budget_exceeded=true` | Prompt test when added |
| Large checkpoint value | Compact inside mission continuation | `tests/test_prompt.py` |
| Metadata inspection | No prompt content or secrets in metadata | `tests/test_prompt.py` |

### 5. Good/Base/Bad Cases
- Good: expose compact memory/skill indexes and let the model call tools for details.
- Base: keep deterministic block ordering for cache reuse.
- Bad: append large raw trajectories into the stable prefix.
- Bad: remove provider-native tool schemas when dropping prompt tool cards.

### 6. Tests Required
- Block order and cache segment tests.
- Metadata shape tests that exclude raw content.
- Budget tests that assert required blocks remain and optional blocks are recorded as dropped.
- Runtime/provider tests that assert prompt metadata is persisted in `prompt.assembled`.

### 7. Wrong vs Correct
#### Wrong
```python
blocks.append(PromptBlock(id="history.raw", content=dumps(full_run_trace), can_drop=False, ...))
```

#### Correct
```python
blocks.append(PromptBlock(id="memory.index", content=compact_cards, can_drop=True, ...))
```
