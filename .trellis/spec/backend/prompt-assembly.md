# Prompt Assembly Contracts

## Scenario: Cache-Friendly Prompt Assembly And Bootstrap Context

### 1. Scope / Trigger
- Trigger: changes to `mnemo/prompt/assembly.py`, `mnemo/prompt/bootstrap.py`, runtime prompt calls, prompt metadata, or provider message assembly.
- Goal: keep prompts stable for KV-cache reuse while injecting bounded user/workspace bootstrap context and limiting optional context growth.

### 2. Signatures
- `load_prompt_bootstrap(state_dir: str | Path, *, workspace_root: str | Path | None = None, per_file_char_limit=BOOTSTRAP_FILE_CHAR_LIMIT, total_char_limit=BOOTSTRAP_TOTAL_CHAR_LIMIT) -> PromptBootstrapContext`
- `mnemo.core.injection.injection_warnings(value: str) -> list[str]`
- `mnemo.runtime.learning.learning_reflection_messages(packet: dict[str, Any]) -> list[dict[str, str]]`
- `PromptAssembler.assemble(current_user_message: str, *, mission=None, checkpoint=None, tool_specs=None, soul_context=None, workspace_context=None, memory_snapshot=None, memory_cards=None, skill_cards=None, scheduled_items=None, runtime_context=None, token_budget=DEFAULT_PROMPT_TOKEN_BUDGET, mode: PromptMode = "full") -> AssembledPrompt`
- `AssembledPrompt.messages() -> list[dict[str, str]]`
- `AssembledPrompt.metadata() -> dict[str, Any]`

### 3. Contracts
- Stable prefix blocks must stay ordered before dynamic blocks.
- Stable prefix order: `system.identity`, `developer.operating_principles`, optional `soul.user_contract`, `tools.cards`.
- Non-droppable blocks: `system.identity`, `developer.operating_principles`, optional `soul.user_contract`, `mission.continuation`, `runtime.context`, `turn.current_user_message`.
- Droppable blocks: optional tool cards, workspace bootstrap blocks, L1 memory snapshot, memory index, and skill index.
- `full` preserves the standard personal prompt surface.
- `minimal` includes identity, operating principles, visible tool cards, `AGENTS.md`/`TOOLS.md` workspace bootstrap, mission continuation, runtime context, and current turn; it does not inject Soul, L1 memory, memory index, or skill index.
- `capsule` includes identity, operating principles, visible tool cards, mission continuation, runtime context, and current turn; it does not inject Soul, workspace bootstrap, L1 memory, memory index, or skill index.
- `none` is diagnostic-only prompt assembly with identity and current turn; runtime execution must reject it.
- `runtime.context` is a turn-scoped non-droppable block for executable prompt modes. It includes current date, local time, timezone/UTC offset, and explicit user location when configured.
- Missing user location must be rendered as not provided; prompt assembly must not infer location from server placement, old memories, or unrelated context.
- Runtime context prompt text must instruct the model to resolve relative dates and freshness terms from the current date, and to avoid stale search years unless the user asks for a specific year.
- Runtime context metadata may include current date, timezone, and a location-known flag, but must not include the raw location string.
- `metadata()` includes `mode`, `execution_allowed`, and `disclosure_boundary`.
- `SOUL.md` under `state_dir` becomes `soul.user_contract` with `stable/user_profile`; it is a bounded user contract, not a raw memory dump.
- Workspace bootstrap files from `workspace_root` become quoted `workspace.bootstrap.*` blocks with `daily/daily_context`.
- Workspace bootstrap content must be bounded by per-file and total character caps and may be dropped under prompt budget pressure.
- Bootstrap metadata may include path, truncation flag, char count, and warning labels; it must not include raw file content.
- Bootstrap content that resembles prompt injection, secret requests, or fake tool calls is labeled in metadata and remains quoted context.
- Prompt/bootstrap and memory-write scanning share `mnemo.core.injection.injection_warnings()` for warning label consistency.
- `memory.l1_snapshot` is daily-cache context and must appear before turn-scoped `memory.index`.
- `memory.l1_snapshot` is a compact index, not a replacement for `memory_search` / `memory_read`.
- Runtime may materialize a missing `memory.l1_snapshot` from active pages before assembly so basic identity/preferences can be answered from the progressive memory layer without immediate tool lookup.
- `schedule.active` is a turn-scoped droppable block in `full` mode when active or paused scheduled items exist.
- Runtime and SDK context assembly pass active/paused user-facing Watch/Cron items through `scheduled_prompt_items()` so the model can inspect existing proactive watches/reminders before creating duplicates.
- `schedule.active` includes only compact item ids, kind/status, title, schedule, next run, and bounded instruction previews; it must not include queued run output bodies, proactive delivery bodies, or full feedback history.
- Prompt text should tell the model to answer directly from visible Soul/L1/memory index context when it fully resolves the turn, and reserve retrieval tools for missing, stale, conflicting, or evidence-detail needs.
- `memory.index` consumes `MemoryEngine.context_cards()` output; rejected, tombstoned, archived, private-deleted, and review-gated memory candidates must be filtered before prompt assembly.
- CLI inspection of the same compiled context is read-only: `mnemo memory snapshot`.
- Tool schemas still travel through provider-native tool definitions; dropping `tools.cards` must not remove actual tool availability.
- Learning reflection prompt is a separate compact after-turn request and must not mutate the stable user-facing prompt prefix.
- Learning reflection prompt carries a bounded `<learning_packet>` with current run input/output and compact tool results only.
- Prompt block budgeting only applies to prompt messages; provider-native tool schemas are tracked in `metadata().tool_schema` separately.
- `metadata().tool_schema` contains `count`, ordered `names`, `token_estimate`, and `budget_scope="provider_native"`; it must not contain raw schema payloads.
- Runtime `prompt.assembled` events include compact `tool_bundle` metadata with `bundle_id`, `epoch`, `profile`, `tool_count`, ordered `tool_names`, `schema_token_estimate`, and cache bust reason.
- `prompt.assembled.tool_bundle` must not contain raw `input_schema` payloads.
- Runtime `prompt.assembled` events include compact `provider_capabilities` and `cache_plan` metadata.
- `prompt.assembled.cache_plan.tool_bundle` must not contain raw `input_schema` payloads.
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
| Soul file present | Inject `soul.user_contract` in stable user profile segment before `tools.cards` | `tests/test_prompt.py`, `tests/test_runtime.py`, `tests/test_cli.py`, `tests/test_web.py` |
| Workspace bootstrap present | Inject bounded quoted `workspace.bootstrap.*` blocks with daily cache policy | `tests/test_prompt.py`, `tests/test_runtime.py`, `tests/test_cli.py`, `tests/test_web.py` |
| Suspicious bootstrap content | Preserve warning labels in metadata without raw content | `tests/test_prompt.py` |
| L1 snapshot present | Add `memory.l1_snapshot` with `daily_context` cache segment before `memory.index` | `tests/test_prompt.py` |
| Missing runtime L1 snapshot | Runtime compiles one from active pages and injects it before `memory.index` | `tests/test_runtime.py` |
| Empty L1 snapshot | Do not inject `memory.l1_snapshot` | `tests/test_prompt.py` |
| Memory index cards | Prompt-facing memory cards exclude rejected/tombstoned/review-gated candidates | `tests/test_memory.py`, `tests/test_runtime.py` |
| Runtime context present | Executable prompt modes include turn-scoped current date/time/timezone/location context before the current user turn | `tests/test_prompt.py`, `tests/test_runtime.py` |
| Missing runtime location | Prompt says user location is not provided and metadata omits raw location | `tests/test_prompt.py` |
| Scheduled items present | Full prompt includes compact turn-scoped `schedule.active` context without queued outputs or delivery bodies | `tests/test_prompt.py`, `tests/test_scheduler.py` |
| CLI snapshot inspection | Existing compiled snapshot is inspectable without full page bodies | `tests/test_cli.py` |
| Tight prompt budget with tools | May drop `tools.cards`; tool schema metadata remains present | `tests/test_prompt.py` |
| Prompt inspect metadata | Includes compact tool schema metadata without raw schemas | `tests/test_cli.py` |
| Prompt inspect ToolBundle metadata | Includes compact bundle id/profile/epoch/token estimate without raw schemas | `tests/test_cli.py` |
| Minimal mode | Omits Soul, memory, and skills while preserving provider-native tool schema metadata | `tests/test_prompt.py`, `tests/test_runtime.py`, `tests/test_cli.py` |
| Learning reflection prompt | Uses a bounded packet and provider-native tool schemas instead of embedding candidate schemas in text | `tests/test_runtime.py` |
| Capsule mode | Omits personal and workspace context while keeping task, mission, and allowed tool cards | `tests/test_prompt.py` |
| None mode | Assembles diagnostic shell and marks `execution_allowed=false`; runtime rejects execution | `tests/test_prompt.py` |
| Invalid mode | Reject with validation error | `tests/test_prompt.py` |

### 5. Good/Base/Bad Cases
- Good: expose compact memory/skill indexes and let the model call tools for details.
- Good: load `SOUL.md` and workspace bootstrap as bounded prompt context with explicit authority boundaries.
- Good: keep provider-native tool schemas out of prompt block budgeting and metadata payload bodies.
- Base: keep deterministic block ordering for cache reuse.
- Bad: append large raw trajectories into the stable prefix.
- Bad: treat workspace files as higher-authority instructions than core/developer blocks.
- Bad: remove provider-native tool schemas when dropping prompt tool cards.

### 6. Tests Required
- Block order and cache segment tests.
- Metadata shape tests that exclude raw content.
- Budget tests that assert required blocks remain and optional blocks are recorded as dropped.
- Tool schema budget separation tests that assert compact metadata remains when `tools.cards` is dropped.
- Runtime/provider tests that assert prompt metadata is persisted in `prompt.assembled`.
- Runtime/CLI/Web tests that assert Soul and workspace bootstrap are passed through request boundaries.
- Runtime/provider tests that assert daily L1 memory snapshot content reaches provider messages when present.
- Runtime/provider tests that assert the prompt includes current runtime context before the current user turn.
- Prompt/runtime tests that assert active/paused scheduled items are included as compact turn context when present.
- Runtime/provider tests that assert learning reflection messages contain a compact packet and no raw tool schema payload.
- Prompt mode tests that assert disclosure boundaries for `minimal`, `capsule`, and `none`.

### 7. Wrong vs Correct
#### Wrong
```python
blocks.append(PromptBlock(id="history.raw", content=dumps(full_run_trace), can_drop=False, ...))
```

#### Correct
```python
blocks.append(PromptBlock(id="memory.index", content=compact_cards, can_drop=True, ...))
```
