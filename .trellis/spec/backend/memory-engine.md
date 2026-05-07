# Memory Engine Contracts

## Scenario: Candidate Consolidation Signals

### 1. Scope / Trigger
- Trigger: changes to `mnemo/memory/engine.py`, memory storage APIs, dream consolidation, or memory tool handlers.
- Goal: preserve candidate-first learning while producing explicit provenance signals for reinforcement and conflicts.

### 2. Signatures
- `MemoryEngine.search(query: str, limit: int = 5, *, search_scope: str = "memory", include_tombstoned: bool = False) -> list[dict[str, Any]]`
- `MemoryEngine.plan_query(query: str) -> MemoryQueryPlan`
- `MemoryEngine.search_with_plan(query: str, limit: int = 5, *, search_scope: str = "memory", include_tombstoned: bool = False) -> dict[str, Any]`
- `MemoryEngine.context_cards(query: str, limit: int = 5, *, search_scope: str = "memory", include_tombstoned: bool = False) -> list[dict[str, Any]]`
- `MemoryEngine.write_candidate(run_id: str, claim: str, *, dimension: str | None = None, scope: str = "global", confidence: float = 0.5, evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]`
- `MemoryEngine.ingest_working_notes(limit: int = 20, *, note_ids: list[str] | set[str] | None = None) -> dict[str, Any]`
- `MemoryEngine.promote_candidate(candidate_id: str) -> dict[str, Any]`
- `MemoryEngine.reject_candidate(candidate_id: str, reason: str) -> dict[str, Any]`
- `MemoryEngine.undo_candidate(candidate_id: str, reason: str = "user undo") -> dict[str, Any]`
- `MemoryEngine.tombstone_memory(memory_id: str, reason: str, *, target_type: str = "auto", replacement_id: str | None = None, eval_run_id: str | None = None) -> dict[str, Any]`
- `MemoryEngine.private_delete_memory(memory_id: str, reason: str = "private_delete", *, target_type: str = "auto") -> dict[str, Any]`
- `MemoryEngine.health_report(limit: int = 20) -> dict[str, Any]`
- `MemoryEngine.decay_stale_pages(limit: int = 50, *, now: float | None = None, stale_confidence: float = 0.35) -> dict[str, Any]`
- `MemoryEngine.collect_dream_delta(limit: int = 20, *, since: float | None = None) -> dict[str, Any]`
- `MemoryEngine.build_dream_plan(delta: dict[str, Any], *, limit: int = 20) -> dict[str, Any]`
- `MemoryEngine.dream_maintenance(limit: int = 20, min_confidence: float = 0.7, *, since: float | None = None, persist: bool = True, actions: list[dict[str, Any]] | None = None, plan: dict[str, Any] | None = None) -> dict[str, Any]`
- `MemoryEngine.apply_dream_actions(actions: list[dict[str, Any]], *, limit: int = 20) -> dict[str, Any]`
- `MemoryEngine.dream_status(limit: int = 20) -> dict[str, Any]`
- `MemoryEngine.save_dream_report(report: dict[str, Any]) -> Path`
- `MemoryEngine.load_latest_dream_report() -> dict[str, Any] | None`
- `MemoryEngine.load_dream_report(report_id: str | None = None, *, latest: bool = False) -> dict[str, Any] | None`
- `MemoryEngine.dream_consolidate(limit: int = 20, min_confidence: float = 0.7, *, candidate_ids: list[str] | set[str] | None = None, note_ids: list[str] | set[str] | None = None) -> dict[str, Any]`
- `MemoryEngine.compile_l1_snapshot(limit: int = 50) -> dict[str, Any]`
- `MemoryEngine.load_or_compile_l1_snapshot(limit: int = 50) -> dict[str, Any] | None`
- `MemoryEngine.load_l1_snapshot() -> dict[str, Any] | None`
- `EvalHarness.run_suite("memory-safety") -> SuiteReport`
- `EvalHarness.run_suite("memory-health") -> SuiteReport`
- CLI: `mnemo harness eval memory-safety --json`
- CLI: `mnemo harness eval memory-health --json`
- `StateStore.update_memory_page_confidence(page_id: str, confidence: float) -> None`
- `StateStore.update_memory_page_status(page_id: str, status: str) -> None`
- `StateStore.upsert_memory_page(title: str, content: str, *, scope: str = "global", source_candidate_id: str | None = None, confidence: float = 0.7, status: str = "active", metadata: dict[str, Any] | None = None) -> str`
- `StateStore.list_memory_pages(status: str | None = "active", limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.list_memory_candidates(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.list_memory_backlinks(target_id: str) -> list[dict[str, Any]]`
- `StateStore.add_memory_tombstone(target_id: str, target_type: str, reason: str, *, summary: str = "", target_hash: str | None = None, evidence_run_id: str | None = None, rule: str | None = None, metadata: dict[str, Any] | None = None) -> str`
- `StateStore.get_memory_tombstone(tombstone_id: str) -> dict[str, Any] | None`
- `StateStore.list_memory_tombstones(*, target_id: str | None = None, target_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.search_session_messages(query: str, limit: int = 5) -> list[dict[str, Any]]`
- `StateStore.add_working_note(mission_id: str, run_id: str, content: str, *, metadata: dict[str, Any] | None = None) -> str`
- `StateStore.list_working_notes(status: str | None = "open", limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.update_working_note_status(note_id: str, status: str, *, result: dict[str, Any] | None = None) -> None`
- CLI: `mnemo memory notes [--status STATUS|all] [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo memory list [--kind candidate|page|all] [--status STATUS|all] [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo memory search <query...> [--scope memory|stable|sessions|all] [--limit N] [--debug-query] [--include-tombstoned] [--state-dir DIR] [--json]`
- CLI: `mnemo memory read <memory_id> [--state-dir DIR] [--json]`
- CLI: `mnemo memory links <memory_id> [--direction outgoing|incoming|both] [--state-dir DIR] [--json]`
- CLI: `mnemo memory snapshot [--state-dir DIR] [--json]`
- Web API: `GET /api/memory/ontology`
- Web API: `GET /api/memory/dimension?dimension=<dimension>`
- Web API: `GET /api/memory/item?type=page|candidate&id=<id>`
- CLI: `mnemo memory health [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo memory decay [--limit N] [--stale-confidence FLOAT] [--state-dir DIR] [--json]`
- CLI: `mnemo memory tombstone <memory_id> --reason REASON [--target-type auto|candidate|page] [--replacement-id ID] [--eval-run-id RUN_ID] [--state-dir DIR] [--json]`
- CLI: `mnemo memory forget <memory_id> [--reason REASON] [--target-type auto|candidate|page] [--state-dir DIR] [--json]`
- CLI: `mnemo memory tombstones [--target-id ID] [--target-type candidate|page] [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo dream run [--limit N] [--min-confidence FLOAT] [--actions-json JSON_ARRAY] [--state-dir DIR] [--json]`
- CLI: `mnemo dream --now [--limit N] [--min-confidence FLOAT] [--actions-json JSON_ARRAY] [--state-dir DIR] [--json]`
- CLI: `mnemo dream status [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo dream report [REPORT_ID|--latest] [--state-dir DIR] [--json]`
- CLI: `mnemo schedule add --kind dream [--schedule SCHEDULE] [--next-run-at TIME] [--dream-limit N] [--dream-min-confidence FLOAT] [--state-dir DIR] [--json]`; omitted `--schedule` defaults to `daily`.
- SDK/HTTP: `schedule_dream(schedule="daily", next_run_at=None, limit=20, min_confidence=0.7)` registers a Dream scheduled item without executing maintenance.
- MCP tool: `mnemo_dream_schedule(schedule="daily", next_run_at=None, limit=20, min_confidence=0.7, source="mcp")`

### 3. Contracts
- `mnemo/memory/engine.py` is a compatibility facade only; domain behavior lives in focused modules under `mnemo/memory/`.
- Memory module ownership:
  - `base.py`: shared store lookup helpers.
  - `recall.py`: query planning facade, memory/session search, prompt context cards, associative page expansion.
  - `learning.py`: W0 ingestion, candidate writes, promotion/rejection/undo, L1 snapshot, deterministic consolidation.
  - `curation.py`: tombstone, replacement links, harmful eval case routing, private delete redaction.
  - `health.py`: memory health cards, score, stale/decay decisions.
  - `dream.py`: Dream delta, model action execution, persisted reports, Dream status.
  - `cards.py`: compact read-model/result shape builders.
  - `quality.py`: deterministic candidate quality signals for specificity, personalization, persistence, actionability, and verifiability.
  - `snapshot.py`: compact L1 memory snapshot compiler for active-page cards, alias pointers, and association hubs.
  - `utils.py` and `constants.py`: dependency-free shared helpers/constants.
- Public imports continue to use `from mnemo.memory import MemoryEngine`; direct engine constants such as `W0_MEMORY_RETENTION` remain re-exported by `mnemo/memory/engine.py` for compatibility.
- Normal tools write memory candidates, not stable pages.
- Normal tools and W0 ingestion write memory candidates through `MemoryEngine.write_candidate()`.
- `MemoryEngine.write_candidate()` normalizes every durable candidate dimension into the configured memory ontology; non-standard labels such as `finance`, `profile`, or `work_style` must not persist as separate user-facing buckets.
- After-turn learning reflection writes memory candidates through the same `memory_write_candidate` tool and `MemoryEngine.write_candidate()` path.
- Candidate writes append compact `memory_safety` evidence with taint, risk, review flag, warning labels, and source summaries.
- Candidate writes append compact `memory_quality` evidence with bounded specificity, personalization, persistence, actionability, verifiability scores, a weighted average, recommendation, and one-line reason.
- Candidate evidence source taint is deterministic and recognizes trusted user/run/work-note sources, external web/file/tool/imported-skill/MCP/runtime sources, and unknown sources.
- Candidate claim/evidence text is scanned for prompt override, secret request, and tool-call injection markers through the shared injection warning helper.
- Candidate writes with injection warnings are marked `needs_review:prompt_injection` and must not be promoted by Dream consolidation.
- Dream consolidation must not promote candidates whose stored quality signal recommends `discard`; these candidates become `rejected:low_quality` with compact quality metadata in the result.
- Dream consolidation may route quality `draft` recommendations to `needs_review:low_quality` instead of promoting them; candidates without a stored quality signal keep the existing compatibility behavior.
- Stable memory pages are created through promotion or explicit curation.
- Active stable memory pages are materialized as deterministic wiki markdown files under `wiki/<dimension>/<title-slug>.md`; stale, archived, and tombstoned pages move to `wiki/_archive/<title-slug>.md`, and private-deleted pages move to `wiki/_redacted/<title-slug>.md`.
- Wiki markdown filenames must be derived from the user-facing page title instead of the opaque page id so file-list disclosure remains semantic; title collisions may append a short id suffix for uniqueness.
- Wiki markdown materialization is triggered by promotion, L1 snapshot compilation, stale/decay status changes, tombstone/archive curation, and private-delete redaction.
- Wiki markdown frontmatter must include compact page metadata: `id`, normalized content `dimension`, `status`, `confidence`, `scope`, timestamps, source candidate id when present, and a content hash.
- Wiki markdown frontmatter must also preserve compact page-local metadata when present: `aliases`, `links`, `associations`, decay/verification hints, exposure hints, and watch ids. These fields remain bounded metadata and must not contain raw evidence blobs or transcript bodies.
- Wiki markdown writes must be atomic and must remove older same-page wiki files from previous dimension/status folders so active recall cannot be visually contradicted by stale files.
- Private-delete redaction must overwrite/remove any pre-existing wiki markdown containing the deleted page id; managed wiki files must not retain the deleted raw body.
- User-facing learning undo uses `MemoryEngine.undo_candidate()` to tombstone the promoted page and candidate through existing curation records.
- W0 working notes are mission-scoped scratchpad entries.
- DreamCycle only turns W0 notes into memory candidates when the note metadata has `retention="memory_candidate"`.
- Daemon recovery may call W0 ingestion with explicit model-marked note ids, but it must not classify or mutate ordinary ephemeral notes.
- W0 ingestion creates draft candidates and marks source notes as `candidate_created`; it never writes stable memory pages directly.
- W0 notes without durable retention are marked `skipped:ephemeral`; short notes are marked `skipped:too_short`.
- `mnemo memory notes` must expose read-only W0 working note inventory for DreamCycle inspection.
- `mnemo memory notes` defaults to open notes; `--status all` means no status filter.
- Duplicate candidates are rejected as `rejected:duplicate`.
- Rejected candidates create a durable `memory_tombstones` row with compact summary, target hash, evidence run id, and do-not-resurrect rule.
- Exact duplicate candidates and conservative near-duplicate candidates may reinforce existing page confidence and must create a `reinforces` memory link.
- Near-duplicate reinforcement requires same normalized memory dimension, non-conflicting polarity, and high keyword overlap/containment; otherwise the candidate remains eligible for conflict detection, promotion, or low-confidence skip.
- Conflicting candidates are not promoted automatically.
- Conflicting candidates are marked `needs_review:conflict` and linked with `conflicts_with`.
- Dream consolidation returns `w0`, `promoted`, `rejected`, `skipped`, `conflicts`, and a compact L1 `snapshot`.
- Dream delta collection returns only bounded W0 notes, draft/review candidates, changed pages, tombstones, recent runs, and health cards since the last persisted Dream report when available.
- Dream plans are model-facing decision surfaces with `decision_owner="model"` and allowed candidate tools; they are advisory and must not encode a mandatory maintenance workflow.
- Dream maintenance may use local deterministic consolidation as fallback, but fallback processing is restricted to collected draft candidate ids and W0 note ids when a delta set is provided.
- Dream maintenance may accept explicit model-proposed action objects through `actions` or `plan.actions` / `plan.maintenance_actions` / native-style `plan.tool_calls`.
- Dream action objects support provider-native shapes (`{"function": {"name": ..., "arguments": ...}}`, `{"type": "tool_use", "name": ..., "input": {...}}`) and compact direct shapes (`{"tool": ..., "arguments": {...}}`).
- `MemoryEngine.apply_dream_actions()` is a bounded executor for safe memory maintenance tools only: `memory_tombstone` and `memory_decay_stale_pages`.
- Dream action execution must call existing MemoryEngine primitives and must not implement a separate workflow router.
- Unsupported, malformed, missing-id, or service-error Dream actions are recorded under `execution.result.actions.skipped` with compact error metadata and must not abort the Dream report.
- Dream `memory_tombstone` actions support low-usefulness archival, harmful tombstone eval routing, and replacement links through `tombstone_memory()`.
- Dream action result payloads must contain ids, statuses, counts, and compact eval/replacement metadata only; they must not copy full memory bodies or raw transcripts.
- Dream reports are compact JSON documents persisted under `runs/dream-reports/` with `delta`, `plan`, `execution`, and `health_after`.
- Due Dream scheduled items run `MemoryEngine.dream_maintenance()` with compact budget metadata and persist the latest report card on the scheduled item.
- MCP Dream registration is a thin facade over `ScheduleService.add_dream()` and must not bypass the scheduled maintenance path.
- SDK/HTTP Dream registration is the same kind of thin facade; due execution remains `ScheduleService.tick()`.
- Dream scheduled ticks refresh the L1 snapshot through the normal Dream execution result, and tick/report payloads expose only snapshot counts and report ids.
- `mnemo dream status` must be read-only and return latest report metadata plus current backlog counts.
- `mnemo dream report --latest` must load the latest persisted report without recomputing memory maintenance.
- L1 snapshots contain active memory page cards only for `items`: `id`, `title`, `summary`, `scope`, `confidence`, and `updated_at`.
- L1 snapshots may include bounded `pointers` derived from active-page aliases/title triggers and bounded `association_hubs` derived from active `memory_links` plus active wiki metadata links/associations.
- L1 snapshots are stored at `wiki/l1-memory-snapshot.json`.
- Runtime prompt assembly may call `load_or_compile_l1_snapshot()` to materialize a missing L1 snapshot when active memory pages exist; an empty memory store still omits L1.
- Prompt-facing snapshots must omit raw evidence and full page content; pointers and association hubs expose only compact trigger, target, counts, and short association labels.
- Stable memory pages may carry compact `metadata` for maintenance hints such as `expires`, `expires_at`, `decay_days`, `last_verified_at`, and `verified_at`.
- Stable memory pages may carry compact `metadata.aliases`, `metadata.links`, and `metadata.associations`; these fields are recall hints, not authoritative facts.
- `MemoryEngine.decay_stale_pages()` inspects active pages only and applies bounded metadata-driven maintenance; pages without expiry or decay metadata are skipped.
- Expired active pages are marked `stale:expired`.
- Decayed pages reduce confidence by `0.01 * overdue_days` after `decay_days`; pages at or below `stale_confidence` are marked `stale:decay`.
- `decay_stale_pages()` returns `memory_decay_report` with compact counts, changed page ids/titles, confidence deltas, reasons, and review cards; it must not include raw evidence or full page bodies.
- `MemoryEngine.health_report()` surfaces `decay_due_active` and `expired_active` counts plus advisory review cards without mutating memory.
- Dream plans may include the `memory_decay_stale_pages` tool when health counts show decay-due active pages; the model still decides whether to run it.
- `MemoryEngine.search()` may include `linked_page` results by following one hop from matching active pages through outgoing links and backlinks.
- `MemoryEngine.search()` also expands one hop through active-page `metadata.links` and `metadata.associations`, resolving targets by active page id, wiki path, title slug, or alias.
- `MemoryEngine.search()` should retrieve active pages whose compact `metadata.aliases` match the planned query route even when the alias does not appear in title/content.
- `linked_page` results must be active pages, bounded by the search limit, deterministic, and de-duplicated from seed page/candidate ids.
- `linked_page` results may include compact `why_relevant` and `association_path` metadata when the link source provides a reason; this metadata is advisory and must not be treated as fact.
- Prompt-facing context cards for `linked_page` include compact `summary`, `relation`, `linked_from`, optional `why_relevant`, and optional `association_path`, not raw evidence.
- Prompt-facing context cards must include only active pages, linked active pages, draft candidates, or non-tombstoned session snippets; rejected, tombstoned, archived, private-deleted, and review-gated candidates must not be injected into prompts through `MemoryEngine.context_cards()`.
- `MemoryEngine.search(search_scope="memory")` preserves the default stable-memory behavior: active pages, candidates, and one-hop linked pages.
- `MemoryEngine.search(search_scope="stable")` is accepted as an alias of `memory`.
- `MemoryEngine.search(search_scope="sessions")` returns L4 `session_message` snippets from prior run messages without page/candidate results.
- `MemoryEngine.search(search_scope="all")` includes stable memory results and session snippets.
- Session recall suppresses snippets that match durable memory tombstones by default so rejected/deleted facts do not re-enter model context through L4.
- `include_tombstoned=True` is an explicit historical lookup opt-in for `search_scope="sessions"` or `"all"`; prompt-facing results remain compact snippets and still omit raw transcript content.
- `MemoryEngine.search_with_plan()` includes compact `recall_policy.tombstone_filter` metadata for session searches: enabled flag, tombstone count, suppressed count, and bounded suppressed item provenance.
- `MemoryEngine.plan_query()` returns a compact deterministic plan with original, lexical, semantic, alias, temporal, dimension, clarification, and route fields.
- Query planning preserves the original user language and exact proper nouns as lexical routes.
- Query planning may use L1 snapshot pointers and association hubs to add alias routes without scanning or injecting full memory pages.
- Query planning maps common Chinese identity/name questions such as `我叫什么`, `我的名字是什么`, and `我是谁` to the `identity` dimension and compact name/profile lexical routes.
- The first QueryPlanner implementation is deterministic and dependency-free; vector embedding, reranking, and model-led spreading activation remain extensions.
- `MemoryEngine.search_with_plan()` returns `query_plan` plus `matches`; `MemoryEngine.search()` preserves the list-only compatibility wrapper.
- Multi-route page, candidate, and session retrieval is fused by reciprocal-rank-style scoring and compact de-duplication.
- Memory match annotations include retrieval score, matched routes, detected dimensions, temporal hint, stale flag, and tombstone flag.
- Tombstoned stable pages are moved out of active page search and L1 snapshot compilation.
- Durable tombstones are explicit curation records; they do not physically delete memory content unless a future private-delete path provides a redacted summary/hash.
- `MemoryEngine.private_delete_memory()` redacts stored candidate claims/evidence or page title/content and writes a compact `private_delete` tombstone with `target_hash`.
- Private-delete tombstone summaries, metadata, health cards, CLI output, and tool evidence must not contain the deleted text.
- Private-deleting a page must also redact its source candidate when `source_candidate_id` is present.
- Private-deleting a candidate must also redact promoted pages found through links or `source_candidate_id`.
- Private-delete L4 suppression uses tombstone `evidence_run_id` provenance for the source run; it must not store raw deleted text just to suppress future recall.
- `MemoryEngine.health_report()` returns compact counts, configured-dimension coverage, scalar component scores, and bounded review cards for model-led memory cultivation.
- `MemoryEngine.health_report()` orphan detection must count both persisted `memory_links` and active-page metadata links/backlinks so wiki-frontmatter associations do not appear as disconnected memory.
- Memory health review cards are advisory input to the model; they do not schedule or execute a fixed maintenance workflow.
- `mnemo memory search --debug-query` includes the compact query plan; default search output remains matches-only.
- `session_message` results contain `id`, `message_id`, `conversation_id`, `mission_id`, `run_id`, `role`, `snippet`, and `created_at`; they must omit raw `content`.
- Prompt-facing context cards for `session_message` include compact `summary` and provenance ids, not full transcripts.
- `memory_read` must read stable memory pages as well as memory candidates.
- `/api/memory/ontology` is the L1 memory disclosure endpoint: it must expose the configured ten-dimension memory coverage as compact counts, short summaries, and per-dimension drill-down URLs only.
- `/api/memory/ontology` must normalize non-standard historical dimension labels into the configured ten dimensions and must never return extra user-facing dimensions.
- `/api/memory/ontology` must be read-only and must not expose provider secrets, raw evidence blobs, unbounded memory bodies, or per-item detail arrays.
- `/api/memory/dimension` is the L2 memory disclosure endpoint: it returns active stable pages and open draft/review candidates for one normalized dimension as clipped cards with detail URLs.
- `/api/memory/dimension` must exclude promoted, rejected, tombstoned, archived, and private-deleted candidates from the user-facing candidate list.
- `/api/memory/item` is the L3 memory disclosure endpoint: it returns one selected page or candidate with clipped detail and compact evidence/tombstone rows.
- `/api/memory/item` markdown for stable pages must read the materialized wiki markdown file directly from disk and must not call a provider on the read path; missing files may be re-materialized from the page record before reading.
- `/api/memory/item` markdown must render as a compact wiki note: YAML frontmatter, one concise H1 topic, body content, optional evidence bullets for candidates, and no API-style field dump.
- `/api/memory/item` markdown uses normalized ontology dimensions in frontmatter, title-based `wiki_path`, and must not repeat the same candidate claim as both title and body.
- `/api/memory/item` cross-entry Markdown anchors must use title-based wiki file paths such as `wiki/<dimension>/<title-slug>.md` instead of generated `#hash` targets.
- `/api/memory/ontology` and `/api/memory/dimension` may deduplicate exact duplicate memory bodies across dimensions for display, preferring the configured ontology order without mutating stored pages.
- `/api/memory/item` must only read active pages and open draft/review candidates; historical rejected/tombstoned/private records require explicit CLI or memory search paths.
- L4 raw session recall remains available only through explicit memory/session search paths, never through the memory compass ontology, dimension, or item endpoints.
- `mnemo memory list` must expose read-only candidate/page inventory for human and harness inspection without mutating memory state.
- `mnemo memory list` defaults to draft candidates; page listing defaults to active pages.
- `mnemo memory list --status all` means no status filter.
- `mnemo memory read` must expose the same candidate/page read behavior for human and harness inspection without mutating memory state.
- `mnemo memory links` must expose read-only outgoing and incoming memory graph edges without mutating memory state.
- `mnemo memory links` should not require the id to resolve as a candidate/page; an empty graph result is valid.
- `mnemo memory snapshot` must load the existing L1 snapshot without regenerating it.
- `mnemo memory snapshot` must report `exists=false` for missing or invalid snapshot files without failing.
- `mnemo memory health` must inspect memory state without mutating it.
- `mnemo memory tombstone` must update the candidate/page status and create a durable tombstone record.
- `reason=low_usefulness` archives a candidate/page with `archived:low_usefulness`; active page search and L1 snapshots must omit archived pages.
- `replacement_id`, when supplied, must resolve to an existing candidate/page, persist compact replacement metadata, and create a `superseded_by` memory link from the curated item to the replacement.
- `reason=harmful` creates a compact draft `memory_harmful_regression` eval case when a source run is available from the candidate, source candidate, ToolHarness context, or CLI `--eval-run-id`.
- Harmful memory eval cases target suite `memory-core`, reference tombstone id and memory id, and must not include full memory bodies or raw transcripts.
- `mnemo memory tombstones` must expose durable tombstone records without loading raw page/candidate bodies beyond compact summaries.
- The `memory-safety` eval suite must remain deterministic and local.
- The `memory-safety` eval suite covers candidate-first writes, conflict guardrails, compact prompt payloads, duplicate reinforcement, and prompt-injection scanner gating.
- The `memory-health` eval suite must remain deterministic and local.
- The `memory-health` eval suite covers tombstone-based wrong-memory suppression, low-confidence over-personalization no-promotion, conflict review cards, and compact health reports.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Empty candidate | `rejected:empty` | `tests/test_memory.py` |
| Safe candidate write | Draft candidate with low-risk `memory_safety` evidence | `tests/test_memory.py` |
| Candidate quality signal | Candidate write appends compact `memory_quality` evidence and result metadata | `tests/test_memory.py` |
| Low-quality candidate | Dream consolidation rejects stored discard-quality candidates without creating a stable page | `tests/test_memory.py` |
| Injected candidate write | `needs_review:prompt_injection` with high-risk safety evidence | `tests/test_memory.py`, `tests/test_tools.py` |
| After-turn memory candidate | Mixed learning reflection can create a memory candidate and chip through the normal write pipeline | `tests/test_runtime.py` |
| Exact duplicate of active page | Reject candidate, raise page confidence, add `reinforces` link | `tests/test_memory.py` |
| Near duplicate of active page | Same-dimension, same-polarity near duplicate reinforces the active page instead of creating a second stable page | `tests/test_memory.py` |
| Obvious contradiction | Mark `needs_review:conflict`, add `conflicts_with` link, do not promote | `tests/test_memory.py` |
| Low confidence non-conflict | Keep `draft`, return skipped entry | `tests/test_memory.py` |
| High confidence non-conflict | Promote to active memory page | `tests/test_memory.py` |
| Learning undo | Tombstone an accepted candidate and its linked stable page | `tests/test_memory.py`, `tests/test_web.py` |
| W0 note with memory retention | Create candidate, mark note `candidate_created`, continue normal consolidation | `tests/test_memory.py` |
| W0 note without memory retention | Mark note `skipped:ephemeral`, create no candidate | `tests/test_memory.py` |
| Daemon W0 recovery | Only model-marked W0 notes are ingested; ephemeral notes remain open | `tests/test_daemon.py`, `tests/test_cli.py` |
| CLI W0 note list | Open and processed working notes can be inspected without mutation | `tests/test_cli.py` |
| Missing or invalid snapshot file | Return `None` | `tests/test_memory.py` |
| Active and archived pages | Snapshot includes active pages only | `tests/test_memory.py` |
| L1 pointers and hubs | Snapshot includes compact alias pointers and association hubs without raw page bodies | `tests/test_memory.py`, `tests/test_prompt.py` |
| Direct association | Search returns linked active pages that do not match the query text | `tests/test_memory.py` |
| Reverse association | Search returns active pages linked back to the query match | `tests/test_memory.py` |
| Metadata association | Search expands active wiki `metadata.links` and `metadata.associations`, materializes compact frontmatter, and suppresses orphan false positives | `tests/test_memory.py` |
| Association cards | Context cards include relation and relevance metadata without full raw payloads | `tests/test_memory.py` |
| Prompt context card filtering | Rejected, tombstoned, and review-gated candidates stay out of prompt-facing context cards | `tests/test_memory.py` |
| L4 session search | `search_scope="sessions"` returns bounded message snippets and omits raw content | `tests/test_memory.py` |
| Tombstone-aware session recall | Default session/all search suppresses snippets matching tombstones; explicit include returns them for historical lookup | `tests/test_memory.py`, `tests/test_cli.py`, `tests/test_tools.py` |
| Memory page read | `memory_read` can load stable pages by id | `tests/test_tools.py` |
| Memory ontology API | Web settings can inspect L1 ten-dimensional coverage without item arrays | `tests/test_web.py` |
| Memory dimension API | Web settings can inspect one L2 dimension with clipped page/candidate cards | `tests/test_web.py` |
| Memory item API | Web settings can inspect one L3 memory item with compact evidence | `tests/test_web.py` |
| CLI memory list | Candidate/page listing uses status defaults and `all` filter | `tests/test_cli.py` |
| CLI memory read | Candidate and page ids return typed memory payloads | `tests/test_cli.py` |
| CLI memory links | Outgoing and incoming links can be inspected by id | `tests/test_cli.py` |
| CLI memory snapshot | Existing L1 snapshot can be inspected without full page bodies | `tests/test_cli.py` |
| Missing L1 snapshot at runtime | First prompt materializes a compact L1 snapshot when active pages exist | `tests/test_runtime.py`, `tests/test_memory.py` |
| Memory safety eval suite | `harness eval memory-safety --json` passes with deterministic local cases | `tests/test_harness.py`, `tests/test_cli.py` |
| Memory health eval suite | `harness eval memory-health --json` passes and release gates include it | `tests/test_harness.py`, `tests/test_cli.py` |
| Prompt injection safety eval | Memory-safety suite includes a no-promotion injected external evidence case | `tests/test_harness.py` |
| Query planning | Plan reports routes, dimensions, and temporal hints without external dependencies | `tests/test_memory.py` |
| Chinese identity query | `我叫什么` maps to identity/name routes and finds profile memory | `tests/test_memory.py` |
| Fused retrieval | Dimension routes can recover relevant pages and annotate matched routes | `tests/test_memory.py` |
| Tombstone annotation | Rejected/tombstoned candidates are marked advisory tombstones | `tests/test_memory.py` |
| Candidate rejection tombstone | Rejected candidates get durable tombstone rows | `tests/test_memory.py` |
| Page tombstone | Page status becomes `tombstoned:<reason>` and active recall omits it | `tests/test_memory.py` |
| Low-usefulness archive | Candidate/page status becomes `archived:low_usefulness`, pages leave active recall/L1, and tombstone provenance remains | `tests/test_memory.py`, `tests/test_cli.py` |
| Replacement curation | Optional replacement id creates compact metadata and a `superseded_by` memory link | `tests/test_memory.py`, `tests/test_cli.py`, `tests/test_tools.py` |
| Harmful memory eval routing | Harmful tombstone creates a compact draft memory-core eval case when a run id is available | `tests/test_memory.py`, `tests/test_cli.py`, `tests/test_tools.py` |
| Private delete redaction | Page/candidate content is redacted, minimal tombstones remain, and source-run session snippets are suppressed | `tests/test_memory.py`, `tests/test_cli.py`, `tests/test_tools.py` |
| Memory health report | Counts, coverage, score, and review cards stay compact | `tests/test_memory.py` |
| Metadata-driven decay | Expired pages become `stale:expired`, overdue low-confidence pages become `stale:decay`, fresh pages remain active | `tests/test_memory.py` |
| Decay health cards | Health report surfaces decay-due cards without mutation | `tests/test_memory.py` |
| CLI memory decay | `mnemo memory decay` emits compact JSON/plain reports and marks stale pages | `tests/test_cli.py` |
| Tool memory decay | `memory_decay_stale_pages` mutates through ToolHarness and returns compact evidence | `tests/test_tools.py` |
| Dream delta-limited maintenance | Old candidates before `since` remain draft while delta candidates are processed | `tests/test_memory.py` |
| Dream model actions | Explicit model-proposed memory actions are applied before local fallback and report compact applied/skipped results | `tests/test_memory.py`, `tests/test_cli.py` |
| Dream native tool-call action | Native-style function/tool-call actions can run safe memory maintenance tools | `tests/test_memory.py` |
| Dream report persistence | Latest report reloads with delta, plan, execution, and health payloads | `tests/test_memory.py`, `tests/test_cli.py` |
| Dream scheduled maintenance | Due dream scheduled item runs Dream maintenance, persists report, refreshes L1 snapshot, and advances/completes schedule | `tests/test_scheduler.py`, `tests/test_cli.py` |
| MCP Dream scheduling | MCP tool creates a Dream scheduled item and due tick runs through existing scheduler | `tests/test_mcp.py` |
| SDK/HTTP Dream scheduling | Core API registers a Dream scheduled item and keeps response compact | `tests/test_sdk.py`, `tests/test_web.py` |
| CLI Dream status/report | `dream status`, `dream report --latest`, and `dream --now` use compact persisted reports | `tests/test_cli.py` |
| CLI query debug | `--debug-query` includes query plan metadata while default JSON omits it | `tests/test_cli.py` |
| CLI health and tombstones | Health, tombstone, and tombstone listing commands normalize output/errors | `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: use links to preserve why memory changed.
- Good: store scanner output as compact evidence on the candidate instead of adding a separate workflow.
- Good: use one-hop page links to surface adjacent wiki knowledge while keeping tool schemas unchanged.
- Good: require explicit `search_scope="sessions"` for raw-session recall so default memory search stays lightweight.
- Good: suppress tombstoned facts at the L4 recall boundary by default, with explicit historical opt-in.
- Good: keep user inspection progressive: L1 coverage first, L2 dimension cards on click, L3 evidence only for a selected item.
- Good: expose query plans as compact metadata so the model can decide whether to refine, read, or ask the user.
- Good: expose health cards as compact model input so the model chooses whether to verify, link, archive, or ignore.
- Good: expose decay as a bounded tool the model may call after seeing health cards, not as an always-on workflow.
- Good: apply explicit Dream maintenance actions through existing MemoryEngine tools and record skipped action reasons compactly.
- Good: persist Dream reports as compact managed-state JSON so status/report inspection does not require another schema surface.
- Good: schedule Dream as a bounded maintenance trigger while keeping consolidation/actions inside MemoryEngine.
- Base: deterministic dream fallback may execute the current delta while provider-led Dream runs are not yet wired.
- Base: deterministic QueryPlanner is a retrieval helper, not a mandatory pre-run workflow.
- Bad: overwrite an active memory page directly from a conflicting candidate.
- Bad: bypass `MemoryEngine.write_candidate()` from tools or W0 ingestion.
- Bad: hide reinforcement or conflict decisions without a memory link.
- Bad: treat advisory tombstone annotations as durable deletion records.
- Bad: let tombstoned stable pages remain in active recall or L1 snapshots.
- Bad: let Dream fallback scan every draft candidate after a delta set is available.
- Bad: encode Dream as a fixed daily workflow that archives/promotes/links every category in a predetermined order.

### 6. Tests Required
- Promotion creates page, updates candidate status, and creates `promoted_to`.
- Learning undo tombstones promoted pages and candidates through existing tombstone APIs.
- W0 ingestion creates candidates from model-marked working notes and skips ephemeral notes.
- Daemon W0 recovery covers model-marked notes without mutating ephemeral notes.
- Candidate writes cover trusted/low-risk and injected/high-risk safety scans.
- Candidate writes cover quality evidence, low-quality rejection, and no stable-page creation for discarded quality signals.
- CLI `memory notes` covers default open notes, unfiltered notes, metadata/result payloads, and compact non-JSON rows.
- Duplicate and conservative near-duplicate reinforcement update confidence and create `reinforces`.
- Conflict review creates `conflicts_with` and leaves the active page unchanged.
- Search/context cards remain compact and omit raw evidence.
- Associative recall covers direct links, backlinks, archived-page filtering, and compact context cards.
- L4 session search covers explicit session scope, compact context cards, and omission of raw message content.
- Tombstone-aware L4 recall covers default suppression, `search_scope="all"` suppression, CLI/tool opt-in, and compact suppression metadata.
- QueryPlanner covers lexical/dimension/temporal route generation, fused retrieval annotations, and CLI debug output.
- Durable tombstones cover candidate rejection, explicit page tombstone, filtered tombstone listing, and compact read payloads.
- Selective forgetting covers `low_usefulness` archival, replacement links, and harmful memory eval routing through MemoryEngine, CLI, and ToolHarness.
- Private delete covers page/candidate redaction, source candidate/page redaction, source-run L4 suppression, CLI output, and compact tool evidence.
- Memory health covers counts, coverage, review cards, compact tool evidence, and CLI output.
- Memory decay covers page metadata round-trip, expired/stale status changes, L1 active filtering, CLI output, and tool evidence.
- `memory_read` covers both candidates and stable pages.
- CLI `memory list` covers default draft candidates, active pages, unfiltered all inventory, and compact non-JSON rows.
- CLI `memory read` covers candidates, pages, non-JSON output, and missing ids.
- CLI `memory links` covers outgoing-only, incoming-only, both directions, and compact non-JSON rows.
- CLI `memory snapshot` covers missing snapshots, loaded snapshots, and compact non-JSON rows.
- L1 snapshot compile/load behavior is covered, including invalid files.
- Dream maintenance report persistence, status, latest-report CLI, and delta-limited candidate processing are covered.
- Dream maintenance action execution covers low-usefulness tombstone, harmful eval routing, native-style tool-call decay, compact action results, and invalid action skips.
- Dream scheduled maintenance covers CLI creation, due tick execution, latest report persistence, and L1 snapshot refresh.
- Harness suite for memory safety covers candidate-first writes, conflict guardrails, compact prompt payloads, duplicate reinforcement, and prompt-injection scanner gating.
- Harness suite for memory health covers wrong-memory tombstone suppression, low-confidence over-personalization no-promotion, conflict health cards, and compact report payloads.

### 7. Wrong vs Correct
#### Wrong
```python
if conflict:
    store.upsert_memory_page(title, candidate["claim"])
```

#### Correct
```python
store.update_memory_candidate_status(candidate["id"], "needs_review:conflict")
store.add_memory_link(candidate["id"], page["id"], "conflicts_with")
```
