# Tool Harness Contracts

## Scenario: Built-In Tool Surface

### 1. Scope / Trigger
- Trigger: any change to `mnemo/tools/registry.py`, `mnemo/tools/standard.py`, `mnemo/core/models.py` tool models, or provider/runtime tool-loop payloads.
- Goal: keep the tool surface model-driven, provider-native, compact, and policy-gated without introducing workflow routers.

### 2. Signatures
- `ToolRegistry.specs() -> list[ToolSpec]`
- `ToolRegistry.from_store(store: StateStore) -> ToolRegistry`
- `ToolRegistry.load_generated_tools(generated_tools: Iterable[dict[str, Any]]) -> None`
- `ToolRegistry.tool_bundle(profile="full.v1", provider_adapter_version="local", schema_serializer_version="mnemo.tool_schema.v1", selected_tool_names=None, epoch=1, cache_bust_reason="initial") -> ToolBundle`
- `ToolBundle.metadata() -> dict[str, Any]`
- `ToolRegistry.execute(call: ToolCallEnvelope, context: ToolContext) -> ToolResult`
- `mnemo.core.workspace.default_workspace_root(state_dir=DEFAULT_STATE_DIR) -> Path`
- `mnemo.core.workspace.resolve_workspace_root(workspace_root, state_dir=DEFAULT_STATE_DIR) -> Path`
- `ToolHarness.execute(call: ToolCallEnvelope, *, run_id: str, mission_id: str) -> ToolResult`
- `ToolExecutionPolicy.check(spec: ToolSpec) -> ToolPermission`
- `tool_specs_as_json_schema(specs: list[ToolSpec]) -> list[dict[str, Any]]`
- `compact_tool_result(result: ToolResult) -> dict[str, Any]`
- `mnemo.runtime.learning.build_learning_packet(store, run_id, *, response=None, tool_results=None) -> dict[str, Any]`
- `mnemo.runtime.learning.learning_reflection_messages(packet: dict[str, Any]) -> list[dict[str, str]]`

### 3. Contracts
- `ToolSpec.name`: unique provider-facing function name.
- `ToolSpec.risk`: one of `read`, `write`, `external`, `admin`.
- `ToolSpec.input_schema`: JSON-schema-compatible object with `additionalProperties: false`.
- `ToolCallEnvelope.arguments`: already parsed dict from the provider-native tool call.
- `ToolResult.result`: full persisted payload for ledger and replay.
- `ToolResult.summary` and `ToolResult.evidence`: compact model/UI payloads.
- `ToolContext.workspace_root`: resolved user workspace root for local file and shell tools.
- Default runtime policy allows `read`, `write`, `external`, and `admin` risks so the normal single-chat user experience does not stall on approval cards.
- Approval cards are still created when a caller explicitly supplies a stricter `ToolExecutionPolicy` that denies `external` or `admin` risks.
- If no workspace is explicitly supplied, local file/shell tools must use `<state_dir>/workspace`, not the process current directory or source repository root.
- Provider-native tool schemas are sent through adapter requests, not embedded as raw prompt blocks or prompt metadata.
- Provider-native tool schemas are grouped into deterministic `ToolBundle` objects with a stable `bundle_id`, `epoch`, `profile`, `provider_adapter_version`, `schema_serializer_version`, ordered `tool_names`, and compact `schema_token_estimate`.
- Runtime ToolBundles use `ProviderCapabilities.adapter_version` for `provider_adapter_version`.
- `ToolBundle.metadata()` must not contain raw `input_schema` payloads.
- Default `full.v1` bundles preserve the existing complete tool surface.
- `minimal.v1` and `capsule.v1` bundles expose only low-risk read/discovery tools by default; model-requested expansion can add more tool schemas in a later provider round.
- `learning.v1` bundles expose only `memory_write_candidate`, `skill_propose_candidate`, `tool_propose_candidate`, `eval_propose_case`, and `learning_discard`.
- After-turn learning reflection uses a `learning.v1` ToolBundle and the normal provider-native tool call + ToolHarness execution boundary.
- After-turn learning reflection must pass a structure-only evidence gate before the second provider call: reflect when the packet already has learning candidates or at least three non-learning tool results; otherwise persist `learning.reflection.skipped`.
- The learning reflection gate must not use user-message keyword lists or language-specific text matching.
- Learning debt review may run after a low-signal turn only when recent completed turns in the same conversation have accrued without learning candidates or a prior debt review barrier.
- Learning debt review must build a compact multi-run packet from run summaries and compact tool-result metadata, then use the same `learning.v1` provider-native tools and ToolHarness path; the runtime must not classify raw text with keyword rules.
- A completed learning debt review is a structural barrier so ordinary low-signal turns do not repeatedly trigger the same multi-run review.
- `tool_search(query?, risk?, limit=20)` returns compact tool cards without raw schemas.
- `tool_expand_schema(names)` returns matching tool names for the runtime to add to the next provider `ToolBundle` epoch; it does not return raw schemas to the model.
- Provider runtime records `tool_bundle.expanded` with `cache_bust_reason="lazy_schema_expansion"` when a successful `tool_expand_schema` call changes the active bundle.
- Provider runtime defaults `max_tool_rounds` to 12 and resolves overrides from CLI/Web runtime config, `MNEMO_MAX_TOOL_ROUNDS`, or settings `runtime.max_tool_rounds`; accepted values are bounded to 1..64.
- Provider runtime treats `ProviderAgentRuntime(max_tool_rounds=N)` as a bounded tool-round budget, not as a hard failure boundary for already gathered evidence. A provider may still return multiple tool calls in one allowed round.
- If the provider still requests tools in the final allowed tool round, runtime executes those tool calls, records `provider.tool_budget_exhausted`, appends a developer instruction to stop calling tools, and performs one final provider request with `tools=()` and `metadata.tool_budget_exhausted=true`.
- Tool calls returned during the no-tool finalization pass are ignored and recorded as `provider.tool_call_ignored`; a run must not emit `run.error` solely because the tool budget was exhausted after successful tool results.
- If the no-tool finalization pass emits text that is only unexecuted tool-call markup, runtime must suppress that literal markup and return a compact fallback summary from executed tool results.
- `artifact_update` returns artifact id, title, and kind; artifact body remains in storage.
- `memory_search` may return `linked_page` matches from one-hop memory associations.
- `memory_search.search_scope`: optional, one of `memory`, `stable`, `sessions`, or `all`; default is `memory`.
- `memory_search.include_tombstoned`: optional boolean; default `false`; only set `true` for explicit historical lookup.
- `memory_search` returns compact `query_plan` metadata plus `matches`; the plan contains routes and annotations, not raw transcripts.
- `memory_search(search_scope="sessions")` returns bounded `session_message` snippets with conversation/mission/run/message ids and no raw transcript body.
- `memory_search(search_scope="sessions"|"all")` suppresses tombstone-matching session snippets by default and may include compact `recall_policy.tombstone_filter` metadata.
- `memory_read` reads either a memory candidate or a stable memory page by id.
- `memory_read` includes durable tombstone metadata for the requested id and still requires explicit read intent.
- `memory_health_report(limit=20)` is read-only and returns compact counts, scores, configured-dimension coverage, and bounded review cards.
- `memory_decay_stale_pages(limit=50, stale_confidence=0.35)` is write risk and applies bounded metadata-driven decay/expiry to active memory pages.
- `memory_tombstone(id, reason, target_type="auto", replacement_id?)` is write risk and records durable curation while updating candidate/page status.
- `memory_promote_candidate(id, min_confidence=0.7)` is write risk and validates one model-selected draft candidate before promotion; it may reject, skip, or route conflicts instead of promoting.
- `memory_reject_candidate(id, reason)` is write risk and records a durable rejected candidate tombstone.
- `memory_tombstone` uses `archived:low_usefulness` for low-usefulness curation and records optional replacement metadata/link evidence compactly.
- `memory_tombstone(reason="harmful")` passes ToolHarness `run_id` into MemoryEngine so harmful curation can create compact memory-core eval cases without exposing another schema field.
- `memory_private_delete(id, reason="private_delete", target_type="auto")` is write risk and redacts stored memory text while returning compact tombstone evidence.
- `recall_search(query, scope="all", limit=8)` returns compact actionable cards across knowledge, past work, artifacts, and decisions.
- `recall_search.scope` is one of `all`, `knowledge`, `past_work`, `artifacts`, or `decisions`.
- `recall_search` is read-only and must omit full artifact bodies and raw session transcripts from result cards and compact evidence.
- `recall_search` excludes the active run from past-work session/run matches so the user's recall query does not echo itself.
- `file_patch(path, replacements, replace_all=False)` applies exact UTF-8 text replacements under `ToolContext.workspace_root` and is `admin` risk.
- `file_patch` rejects missing text, ambiguous text when `replace_all` is false, binary files, and paths outside the workspace.
- `web_search(query, limit=5, timeout_s=10)` queries the public web and returns compact result metadata only: title, URL, snippet, and position. It must not fetch result pages or return raw search HTML.
- `web_search` must filter search-engine internal/ad redirect URLs from compact results unless they can be normalized to a public destination URL.
- `web_fetch(url, timeout_s=10, max_bytes=60000)` validates HTTP/HTTPS URLs with a network location before opening a request; malformed URLs and private/internal network targets fail as tool errors without network I/O.
- `web_fetch` returns readable text for HTML pages, preserving compact metadata such as final URL, status, content type, and title; it must reject binary/PDF payloads instead of decoding garbage.
- Compact `web_fetch` evidence must include a bounded readable text excerpt or JSON preview so the next model round can use fetched content without repeatedly calling fetch or shell tools.
- Web tool design acknowledges Hermes Agent's MIT-licensed `tools/web_tools.py` split between search metadata and page extraction/fetching, while keeping Mnemo's implementation stdlib-only and project-specific.
- `browser_open(url, new=2, dry_run=False)` validates HTTP/HTTPS URLs and opens them with the default browser; it is `external` risk.
- `app_open(path, dry_run=False)` resolves `path` under `ToolContext.workspace_root` and opens it with the OS default app; it is `admin` risk.
- Connector tools support `dry_run=True` so tests and model planning can validate the handoff without launching local UI.
- OpenAI-compatible adapters convert `tool_calls[].function` into `ToolCallEnvelope`.
- Anthropic adapters convert `tool_use` content blocks into `ToolCallEnvelope` and return tool results as `tool_result` content blocks.
- `working_note.retention`: optional model decision, either `ephemeral` or `memory_candidate`.
- `working_note` with `retention="memory_candidate"` stores metadata for DreamCycle; it does not create a memory candidate synchronously.
- `memory_write_candidate` must call `MemoryEngine.write_candidate()` so taint scanning and prompt-injection review gates apply consistently.
- `memory_write_candidate` returns `candidate_id`, candidate `status`, and compact `safety` metadata.
- Compact `memory_write_candidate` evidence includes candidate id, status, and compact safety metadata, never raw external evidence text.
- Normal `memory_write_candidate`, `skill_propose_candidate`, `tool_propose_candidate`, and `eval_propose_case` results are unobtrusive: they persist candidates and compact tool evidence without visible confirmation chips.
- Review-gated `memory_write_candidate` results may project `learning.chip.item.requires_confirmation=true` with compact risk/reason metadata and no raw evidence text.
- After-turn learning reflection action events are marked as internal learning events so Web clients can suppress background housekeeping from the main timeline.
- `ask_user` is `write` risk because it persists an Inbox decision item.
- `ask_user` is a last-resort tool for blocked authority, missing information, or irreversible high-impact choices; it must not be used for routine confirmations.
- `ask_user` returns compact decision data with `item_id`, question, reason, status, and natural-language option labels; streamed `decision.card` events must not contain raw tool traces.
- `schedule_list(kind="all", status="active", limit=20)` is read-only and returns compact scheduled-item cards so the model can inspect existing proactive watches/reminders before creating duplicates.
- Empty `schedule_list` compact feedback must explicitly say it only inspected state and that a user-requested new reminder/watch still requires `schedule_watch` or `schedule_cron`.
- `schedule_watch(target, instruction, schedule="daily", next_run_at?)` is write risk and creates a durable model-led Watch through `ScheduleService.add_watch(source="model")`; it registers future work only and must not enqueue or deliver immediately.
- `schedule_cron(message, schedule="once", title?, next_run_at?)` is write risk and creates a durable scheduled Mnemo task through `ScheduleService.add_cron(source="model")`; due execution remains owned by scheduler/proactive tick.
- `schedule_update_status(item_id, status, next_run_at?)` is write risk and can pause, resume, disable, or complete an existing scheduled item; resuming an item without a due time must compute a future/now due time from its schedule.
- Compact scheduled-tool results include item id, kind, title, status, schedule, source, next run, last run, bounded instruction preview, and compact Watch feedback only.
- `watch_feedback(item_id, outcome, decision?)` is `write` risk because it mutates scheduled Watch metadata and may alter schedule/status.
- `watch_feedback` records compact outcome counts/streaks and applies only explicit model/user policy decisions such as `keep`, `sparsify`, `pause`, or `disable`.
- Compact `watch_feedback` results include item id/title, outcome, decision action, status, and schedule, not raw notification bodies or full run traces.
- Due Watch prompts must frame the final assistant response as the exact user-visible push body. They must not ask the model to record routine notified/silent `watch_feedback`; the proactive delivery layer records those outcomes after suppression or successful delivery.
- Denied `external` and `admin` tool calls create persisted Inbox `tool_approval` Decision Cards and must not execute the denied handler.
- Denied high-risk tool results include compact decision metadata and evidence; raw tool schemas and large arguments must not be exposed in streamed cards.
- Accepted open `tool_approval` Inbox decisions execute the stored tool call once through `ToolHarness` with an approval policy limited to the approved tool name.
- Rejected, ignored, malformed, missing-source, unknown-tool, and already-resolved `tool_approval` decisions must not execute tools.
- Approval execution appends `tool.approval.executing` and `tool.approval.executed` around the normal `tool.called` / `tool.result` ledger events and returns compact `tool_result` metadata to CLI/Web callers.
- Skill crystallization is exposed as a normal provider-native tool call; the harness only validates policy, executes the handler, and returns compact summary/evidence.
- `compact_tool_result` for crystallization must not include the generated skill body or raw source run payloads.
- `skill_install(source, force=false)` is exposed as a normal write-risk provider-native tool call; it installs only validated skill directories, zip archives, ClawHub sources, raw `SKILL.md`/Markdown URLs, or git sources through `SkillService.install()`.
- Compact `skill_install` evidence includes installed skill ids, names, statuses, and paths only; it must not include full skill bodies or companion asset contents.
- `skill_patch_candidate` is exposed as a normal provider-native tool call and returns patch metadata, not the patched skill body.
- Active generated tools are loaded from `StateStore.list_generated_tools(status="active")`.
- Generated tools are normal provider-native tools once loaded into `ToolRegistry`.
- Generated tool aliases execute by mapping model arguments to an existing target tool handler.
- Compact results for install/uninstall/rollback and generated tool execution must not include implementation payloads.
- `artifact.card` events carry artifact metadata only; clients fetch body content explicitly when the user opens the artifact.
- `recall.card` events carry recall query metadata and compact cards only; clients reuse existing artifact/decision actions or composer prefill for follow-up work.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Unknown tool name | Raise `ToolError` before handler execution | Registry unit test |
| Disallowed risk | Return `ToolResult(ok=False)`, persist `tool.denied`, do not call handler | `tests/test_tools.py` |
| Default runtime policy | Allows external/admin tools unless a stricter policy is explicitly supplied | `tests/test_tools.py` |
| Explicitly disallowed external/admin risk | Persist `tool_approval` Inbox decision, emit compact decision evidence/card, do not call handler | `tests/test_tools.py`, `tests/test_runtime.py` |
| Disallowed non-high-risk tool | Return normal denial without creating a decision item | `tests/test_tools.py` |
| Accepted tool approval | Execute the stored call once through `ToolHarness` and return compact result metadata | `tests/test_web.py`, `tests/test_cli.py` |
| Rejected or repeated tool approval | Resolve the Inbox item without executing the stored call | `tests/test_web.py`, `tests/test_cli.py` |
| Invalid approval tool | Raise before resolving the Inbox item or executing any handler | `tests/test_approvals.py` |
| Path outside workspace | Return failed tool result with boundary error | `tests/test_standard_tools.py` |
| Missing workspace override | File writes land under `<state_dir>/workspace` | `tests/test_standard_tools.py`, `tests/test_web.py` |
| File patch exact edit | Admin policy applies exact replacement and returns compact patch evidence | `tests/test_standard_tools.py` |
| File patch ambiguity | Reject duplicate old text unless `replace_all=true` | `tests/test_standard_tools.py` |
| Binary file read | Return failed tool result, no decoded payload | `tests/test_standard_tools.py` |
| Shell command timeout | Return failed tool result with timeout error | `tests/test_standard_tools.py` |
| Web fetch malformed URL | Return failed tool result before network I/O | `tests/test_standard_tools.py` |
| Web fetch private URL | Return failed tool result before network I/O | `tests/test_standard_tools.py` |
| Web fetch HTML page | Return readable text and title, not raw HTML tags/scripts | `tests/test_standard_tools.py` |
| Web fetch compact feedback | Provider tool feedback includes bounded text or JSON preview from fetched content | `tests/test_standard_tools.py`, `tests/test_runtime.py` |
| Web search | Return compact search result metadata and evidence | `tests/test_standard_tools.py` |
| Web search ad/internal URLs | Skip search-engine internal ad redirect URLs from result cards | `tests/test_standard_tools.py` |
| Browser connector | External policy gates URL open; dry-run validates HTTP/HTTPS URL without launching browser | `tests/test_standard_tools.py` |
| App connector | Admin policy gates OS app open; path traversal is rejected before opener execution | `tests/test_standard_tools.py` |
| Ask user decision | Creates a persistent Inbox item and returns compact decision evidence | `tests/test_tools.py`, `tests/test_web.py` |
| Schedule tools | Provider-native schedule tools create/list/update compact scheduled items without immediate enqueue/delivery | `tests/test_tools.py`, `tests/test_runtime.py` |
| Watch feedback decision | Applies explicit Watch policy and returns compact evidence | `tests/test_tools.py`, `tests/test_scheduler.py` |
| Provider tool result feedback | Send `compact_tool_result`, not full raw payload | Runtime/provider tests |
| Prompt metadata | Records compact tool schema count/names/estimate without raw schema payloads | `tests/test_prompt.py`, `tests/test_cli.py` |
| Stable ToolBundle | Recompiling the same profile/provider produces the same `bundle_id` and content-free metadata | `tests/test_tools.py` |
| Minimal ToolBundle profile | Omits memory/skill write tools while preserving discovery/read tools | `tests/test_tools.py`, `tests/test_runtime.py` |
| Learning ToolBundle profile | Exposes only mixed learning candidate tools and no discovery/core task tools | `tests/test_tools.py` |
| Tool search | Returns compact tool cards without schemas | `tests/test_tools.py` |
| Lazy schema expansion | Provider runtime creates a new bundle epoch after `tool_expand_schema` | `tests/test_runtime.py` |
| Tool budget exhaustion | Provider runtime executes final-round tool calls, then completes through a no-tool finalization pass instead of failing the run | `tests/test_runtime.py` |
| Tool budget finalization markup | Suppress literal unexecuted tool-call text and return a compact fallback summary | `tests/test_runtime.py` |
| Anthropic tool use | Parse non-streaming and streaming `tool_use` blocks into `ToolCallEnvelope` | `tests/test_providers.py` |
| Anthropic tool result feedback | Convert Mnemo tool messages into Anthropic `tool_result` user blocks | `tests/test_providers.py` |
| Working note memory retention | Persist note metadata and compact evidence only | `tests/test_tools.py` |
| Memory write safety scan | External prompt-injection evidence is stored as `needs_review:prompt_injection` with compact safety evidence | `tests/test_tools.py` |
| Normal learning candidate | Persists candidate/evidence without a visible confirmation chip | `tests/test_runtime.py` |
| Review memory learning chip | Review-gated memory candidates may stream a `learning.chip` that requires review and omits raw evidence | `tests/test_runtime.py` |
| Internal learning actions | After-turn learning action events are marked internal for Web suppression | `tests/test_runtime.py`, `tests/test_web.py` |
| After-turn mixed learning | Provider reflection can propose memory/skill/tool/eval candidates from one compact packet | `tests/test_runtime.py` |
| Low-signal learning skip | Zero/low-tool turns skip the second provider learning call and persist a skip reason | `tests/test_runtime.py` |
| Learning debt review | Recent no-learning completed turns trigger one compact multi-run review through `learning.v1`, then wait behind a debt-review barrier | `tests/test_runtime.py` |
| Skill candidate review | Return compact review status/evidence without body | `tests/test_tools.py` |
| Skill install tool | Install a skill through ToolHarness/ProviderRuntime without a decision card under default write policy and omit skill body from compact evidence | `tests/test_tools.py`, `tests/test_runtime.py` |
| Skill crystallization | Return compact crystallization evidence without body/raw payloads | `tests/test_tools.py` |
| Skill patch candidate | Return compact patch evidence without body and leave source skill unchanged | `tests/test_tools.py`, `tests/test_skills_filesystem.py` |
| Skill eval case run | Return compact eval status/evidence without body | `tests/test_tools.py` |
| Generated tool install | Return compact install evidence without implementation payload | `tests/test_tools.py` |
| Generated tool execution | Execute through existing handler and return generated-tool evidence | `tests/test_tools.py` |
| Generated tool rollback | Mark generated tool and candidate `rolled_back`, drop active alias, and return compact evidence | `tests/test_tools.py` |
| Generated tool runtime exposure | Provider runtime sends active generated tool specs | `tests/test_runtime.py` |
| Artifact card projection | Emit id/title/kind without full artifact body | `tests/test_web.py`, `mnemo/runtime/common.py` |
| Memory page read | Return stable page payload when `memory_read.id` is a memory page id | `tests/test_tools.py` |
| Memory decay tool | Mark expired/decayed active pages stale through ToolHarness and return compact evidence | `tests/test_tools.py` |
| Session memory search | `memory_search` can target L4 snippets through `search_scope="sessions"` | `tests/test_tools.py` |
| Tombstone-aware session search | `memory_search` suppresses tombstoned session snippets by default and honors explicit historical opt-in | `tests/test_tools.py` |
| Memory query plan | `memory_search` result includes compact query plan metadata | `tests/test_tools.py` |
| Memory health report | Return compact health evidence without raw page bodies beyond review summaries | `tests/test_tools.py` |
| Memory tombstone | Write policy records durable tombstone, optional replacement link, harmful eval metadata, and compact evidence | `tests/test_tools.py` |
| Memory private delete | Write policy redacts candidate/page text and returns compact evidence without deleted content | `tests/test_tools.py` |
| Recall search | Return compact actionable cards for memory/session/artifact/decision matches without raw bodies | `tests/test_tools.py`, `tests/test_runtime.py`, `tests/test_web.py` |

### 5. Good/Base/Bad Cases
- Good: add a new tool by defining `ToolSpec`, registering a handler, and adding summary/evidence projection.
- Good: keep memory maintenance tools bounded and compact so the model chooses when to call them.
- Base: read-only tools should be usable by the default policy.
- Good: keep artifact bodies in storage and reference them by id in UI/event payloads.
- Good: expose associative memory through existing memory tools instead of a separate workflow router.
- Good: expose L4 recall through `memory_search` scope instead of adding a separate session workflow tool.
- Good: expose memory maintenance through ordinary read/write tools so the model decides when to call them.
- Good: expose user-facing cross-surface recall through one read-only `recall_search` tool instead of separate dashboard workflows.
- Good: expose Watch self-learning as a normal write tool so the model decides when to sparse, pause, or disable.
- Good: expose large or rare tool surfaces through `tool_search` and `tool_expand_schema` rather than dumping every schema into every reduced prompt mode.
- Good: gate after-turn learning on structured tool/candidate evidence instead of parsing user text.
- Good: represent user approvals as Inbox decision item ids, not transient-only chat text.
- Good: turn blocked external/admin actions into compact Decision Cards instead of executing them.
- Good: use `file_patch` for bounded edits instead of full-file overwrite when the old text is known.
- Good: use connector tools as side-effect handoffs from model decisions, not as workflow branches.
- Bad: adding a handler that performs side effects while declaring `risk="read"`.
- Bad: returning large raw payloads to the model instead of compact summaries and evidence cards.
- Bad: using `app_open` with an unscoped absolute path outside the workspace.

### 6. Tests Required
- Tool policy denial: assert handler is not called and `tool.denied` is recorded.
- Default policy: assert external/admin tools are allowed by default.
- High-risk denial: assert stricter policies still persist `tool_approval` Inbox items and emit `decision.card` without executing the handler.
- High-risk approval: assert an accepted open `tool_approval` item executes once through `ToolHarness`, while rejected and repeated resolutions do not execute.
- Tool success: assert `tool.called`, `tool.result`, `tool_calls` persistence, and compact result shape.
- Memory search session scope: assert session snippets include provenance ids and omit raw content.
- Memory health report: assert compact counts, score, and review-card evidence.
- Memory tombstone: assert status mutation, durable tombstone row, and compact evidence.
- Memory promote candidate: assert model-selected candidate promotion goes through safety/quality/conflict validation and returns compact evidence.
- Memory reject candidate: assert rejected candidate status and tombstone evidence stay compact.
- Memory private delete: assert redaction, compact evidence, related redaction counts, and omission of deleted text.
- Recall search: assert compact cards include `kind`, `item_id`, `title`, `summary`, provenance ids, and action hints while omitting full bodies/transcripts.
- Working note retention metadata: assert stored metadata and compact result remain small.
- Memory write safety scan: assert status, safety risk, review flag, and compact evidence shape.
- Normal learning candidate: assert no visible confirmation chip is streamed for ordinary candidate writes.
- Review memory learning chip: assert `requires_confirmation`, risk/reason metadata, and omission of raw evidence text.
- Internal learning actions: assert background reflection action events carry internal learning metadata for client suppression.
- Skill review: assert status is persisted and compact result omits full skill body.
- Skill install: assert active skill state is persisted and compact result omits full skill body.
- Skill crystallization: assert draft status is persisted and compact result omits raw source payload.
- Skill patch: assert draft status is persisted and compact result omits full skill body.
- Skill eval case: assert eval status is persisted and compact result omits full skill body.
- Generated tool install: assert active tool row is persisted and compact result omits implementation payload.
- Generated tool execution: assert alias argument mapping reaches the target handler.
- Generated tool rollback: assert generated tool/candidate statuses become `rolled_back`, active registry drops the alias, and compact evidence omits implementation payload.
- Artifact update: assert card payload has id/title/kind and omits body content.
- Local path tools: assert workspace scoping and traversal rejection.
- File patch: assert admin gating, exact edit success, path traversal rejection, and ambiguous replacement handling.
- Connector tools: assert default policy denial, dry-run success, compact evidence, URL validation, web fetch text/JSON preview feedback, search ad filtering, and workspace path traversal rejection.
- Ask-user decisions: assert persistent Inbox item id appears in compact evidence and `decision.card` payload.
- Schedule tools: assert model-facing Watch/Cron creation uses `source="model"`, empty list feedback tells the model to create a requested schedule, list output stays compact, update status mutates only the selected scheduled item, and provider runtime exposes/executed schedule tools.
- Watch feedback: assert model policy updates schedule/status and compact evidence omits raw notification bodies.
- Provider runtime: assert tool specs are passed to the adapter and tool results are returned as `role="tool"` messages.
- Provider runtime tool budget: assert final-round tool calls are executed, the final provider request has `tools=()`, metadata includes `tool_budget_exhausted=true`, unexecuted tool-call markup is suppressed, and no `run.error` is emitted when a final response is produced.
- ToolBundle tests: assert stable ids, compact metadata, profile filtering, and lazy expansion epochs.
- After-turn learning tests: assert compact packet reflection uses `learning.v1`, persists lifecycle events, and can produce mixed candidate chips.
- Low-signal learning tests: assert a zero-tool turn does not create an after-turn provider request and records `learning.reflection.skipped`.
- Learning debt tests: assert five recent no-learning turns can trigger one multi-run packet and that a recent debt review suppresses repeated review.
- Anthropic provider: assert tool specs are passed as `tools`, tool results become `tool_result` blocks, and streaming tool deltas are parsed.

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
