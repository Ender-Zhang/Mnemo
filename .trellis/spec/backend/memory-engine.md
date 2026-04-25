# Memory Engine Contracts

## Scenario: Candidate Consolidation Signals

### 1. Scope / Trigger
- Trigger: changes to `mnemo/memory/engine.py`, memory storage APIs, dream consolidation, or memory tool handlers.
- Goal: preserve candidate-first learning while producing explicit provenance signals for reinforcement and conflicts.

### 2. Signatures
- `MemoryEngine.search(query: str, limit: int = 5, *, search_scope: str = "memory") -> list[dict[str, Any]]`
- `MemoryEngine.plan_query(query: str) -> MemoryQueryPlan`
- `MemoryEngine.search_with_plan(query: str, limit: int = 5, *, search_scope: str = "memory") -> dict[str, Any]`
- `MemoryEngine.context_cards(query: str, limit: int = 5, *, search_scope: str = "memory") -> list[dict[str, Any]]`
- `MemoryEngine.write_candidate(run_id: str, claim: str, *, dimension: str | None = None, scope: str = "global", confidence: float = 0.5, evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]`
- `MemoryEngine.ingest_working_notes(limit: int = 20) -> dict[str, Any]`
- `MemoryEngine.promote_candidate(candidate_id: str) -> dict[str, Any]`
- `MemoryEngine.reject_candidate(candidate_id: str, reason: str) -> dict[str, Any]`
- `MemoryEngine.tombstone_memory(memory_id: str, reason: str, *, target_type: str = "auto") -> dict[str, Any]`
- `MemoryEngine.health_report(limit: int = 20) -> dict[str, Any]`
- `MemoryEngine.dream_consolidate(limit: int = 20, min_confidence: float = 0.7) -> dict[str, Any]`
- `MemoryEngine.compile_l1_snapshot(limit: int = 50) -> dict[str, Any]`
- `MemoryEngine.load_l1_snapshot() -> dict[str, Any] | None`
- `EvalHarness.run_suite("memory-safety") -> SuiteReport`
- CLI: `mnemo harness eval memory-safety --json`
- `StateStore.update_memory_page_confidence(page_id: str, confidence: float) -> None`
- `StateStore.update_memory_page_status(page_id: str, status: str) -> None`
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
- CLI: `mnemo memory search <query...> [--scope memory|stable|sessions|all] [--limit N] [--debug-query] [--state-dir DIR] [--json]`
- CLI: `mnemo memory read <memory_id> [--state-dir DIR] [--json]`
- CLI: `mnemo memory links <memory_id> [--direction outgoing|incoming|both] [--state-dir DIR] [--json]`
- CLI: `mnemo memory snapshot [--state-dir DIR] [--json]`
- CLI: `mnemo memory health [--limit N] [--state-dir DIR] [--json]`
- CLI: `mnemo memory tombstone <memory_id> --reason REASON [--target-type auto|candidate|page] [--state-dir DIR] [--json]`
- CLI: `mnemo memory tombstones [--target-id ID] [--target-type candidate|page] [--limit N] [--state-dir DIR] [--json]`

### 3. Contracts
- Normal tools write memory candidates, not stable pages.
- Normal tools and W0 ingestion write memory candidates through `MemoryEngine.write_candidate()`.
- Candidate writes append compact `memory_safety` evidence with taint, risk, review flag, warning labels, and source summaries.
- Candidate evidence source taint is deterministic and recognizes trusted user/run/work-note sources, external web/file/tool/imported-skill/MCP/runtime sources, and unknown sources.
- Candidate claim/evidence text is scanned for prompt override, secret request, and tool-call injection markers through the shared injection warning helper.
- Candidate writes with injection warnings are marked `needs_review:prompt_injection` and must not be promoted by Dream consolidation.
- Stable memory pages are created through promotion or explicit curation.
- W0 working notes are mission-scoped scratchpad entries.
- DreamCycle only turns W0 notes into memory candidates when the note metadata has `retention="memory_candidate"`.
- W0 ingestion creates draft candidates and marks source notes as `candidate_created`; it never writes stable memory pages directly.
- W0 notes without durable retention are marked `skipped:ephemeral`; short notes are marked `skipped:too_short`.
- `mnemo memory notes` must expose read-only W0 working note inventory for DreamCycle inspection.
- `mnemo memory notes` defaults to open notes; `--status all` means no status filter.
- Duplicate candidates are rejected as `rejected:duplicate`.
- Rejected candidates create a durable `memory_tombstones` row with compact summary, target hash, evidence run id, and do-not-resurrect rule.
- Duplicate candidates may reinforce existing page confidence and must create a `reinforces` memory link.
- Conflicting candidates are not promoted automatically.
- Conflicting candidates are marked `needs_review:conflict` and linked with `conflicts_with`.
- Dream consolidation returns `w0`, `promoted`, `rejected`, `skipped`, `conflicts`, and a compact L1 `snapshot`.
- L1 snapshots contain active memory page cards only: `id`, `title`, `summary`, `scope`, `confidence`, and `updated_at`.
- L1 snapshots are stored at `wiki/l1-memory-snapshot.json`.
- Prompt-facing snapshots must omit raw evidence and full page content.
- `MemoryEngine.search()` may include `linked_page` results by following one hop from matching active pages through outgoing links and backlinks.
- `linked_page` results must be active pages, bounded by the search limit, deterministic, and de-duplicated from seed page/candidate ids.
- Prompt-facing context cards for `linked_page` include compact `summary`, `relation`, and `linked_from`, not raw evidence.
- `MemoryEngine.search(search_scope="memory")` preserves the default stable-memory behavior: active pages, candidates, and one-hop linked pages.
- `MemoryEngine.search(search_scope="stable")` is accepted as an alias of `memory`.
- `MemoryEngine.search(search_scope="sessions")` returns L4 `session_message` snippets from prior run messages without page/candidate results.
- `MemoryEngine.search(search_scope="all")` includes stable memory results and session snippets.
- `MemoryEngine.plan_query()` returns a compact deterministic plan with original, lexical, semantic, alias, temporal, dimension, clarification, and route fields.
- Query planning preserves the original user language and exact proper nouns as lexical routes.
- The first QueryPlanner implementation is deterministic and dependency-free; vector embedding, reranking, and model-led spreading activation remain extensions.
- `MemoryEngine.search_with_plan()` returns `query_plan` plus `matches`; `MemoryEngine.search()` preserves the list-only compatibility wrapper.
- Multi-route page, candidate, and session retrieval is fused by reciprocal-rank-style scoring and compact de-duplication.
- Memory match annotations include retrieval score, matched routes, detected dimensions, temporal hint, stale flag, and tombstone flag.
- Tombstoned stable pages are moved out of active page search and L1 snapshot compilation.
- Durable tombstones are explicit curation records; they do not physically delete memory content unless a future private-delete path provides a redacted summary/hash.
- `MemoryEngine.health_report()` returns compact counts, configured-dimension coverage, scalar component scores, and bounded review cards for model-led memory cultivation.
- Memory health review cards are advisory input to the model; they do not schedule or execute a fixed maintenance workflow.
- `mnemo memory search --debug-query` includes the compact query plan; default search output remains matches-only.
- `session_message` results contain `id`, `message_id`, `conversation_id`, `mission_id`, `run_id`, `role`, `snippet`, and `created_at`; they must omit raw `content`.
- Prompt-facing context cards for `session_message` include compact `summary` and provenance ids, not full transcripts.
- `memory_read` must read stable memory pages as well as memory candidates.
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
- `mnemo memory tombstones` must expose durable tombstone records without loading raw page/candidate bodies beyond compact summaries.
- The `memory-safety` eval suite must remain deterministic and local.
- The `memory-safety` eval suite covers candidate-first writes, conflict guardrails, compact prompt payloads, duplicate reinforcement, and prompt-injection scanner gating.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Empty candidate | `rejected:empty` | `tests/test_memory.py` |
| Safe candidate write | Draft candidate with low-risk `memory_safety` evidence | `tests/test_memory.py` |
| Injected candidate write | `needs_review:prompt_injection` with high-risk safety evidence | `tests/test_memory.py`, `tests/test_tools.py` |
| Exact duplicate of active page | Reject candidate, raise page confidence, add `reinforces` link | `tests/test_memory.py` |
| Obvious contradiction | Mark `needs_review:conflict`, add `conflicts_with` link, do not promote | `tests/test_memory.py` |
| Low confidence non-conflict | Keep `draft`, return skipped entry | `tests/test_memory.py` |
| High confidence non-conflict | Promote to active memory page | `tests/test_memory.py` |
| W0 note with memory retention | Create candidate, mark note `candidate_created`, continue normal consolidation | `tests/test_memory.py` |
| W0 note without memory retention | Mark note `skipped:ephemeral`, create no candidate | `tests/test_memory.py` |
| CLI W0 note list | Open and processed working notes can be inspected without mutation | `tests/test_cli.py` |
| Missing or invalid snapshot file | Return `None` | `tests/test_memory.py` |
| Active and archived pages | Snapshot includes active pages only | `tests/test_memory.py` |
| Direct association | Search returns linked active pages that do not match the query text | `tests/test_memory.py` |
| Reverse association | Search returns active pages linked back to the query match | `tests/test_memory.py` |
| Association cards | Context cards include relation metadata without full raw payloads | `tests/test_memory.py` |
| L4 session search | `search_scope="sessions"` returns bounded message snippets and omits raw content | `tests/test_memory.py` |
| Memory page read | `memory_read` can load stable pages by id | `tests/test_tools.py` |
| CLI memory list | Candidate/page listing uses status defaults and `all` filter | `tests/test_cli.py` |
| CLI memory read | Candidate and page ids return typed memory payloads | `tests/test_cli.py` |
| CLI memory links | Outgoing and incoming links can be inspected by id | `tests/test_cli.py` |
| CLI memory snapshot | Existing L1 snapshot can be inspected without full page bodies | `tests/test_cli.py` |
| Memory safety eval suite | `harness eval memory-safety --json` passes with deterministic local cases | `tests/test_harness.py`, `tests/test_cli.py` |
| Prompt injection safety eval | Memory-safety suite includes a no-promotion injected external evidence case | `tests/test_harness.py` |
| Query planning | Plan reports routes, dimensions, and temporal hints without external dependencies | `tests/test_memory.py` |
| Fused retrieval | Dimension routes can recover relevant pages and annotate matched routes | `tests/test_memory.py` |
| Tombstone annotation | Rejected/tombstoned candidates are marked advisory tombstones | `tests/test_memory.py` |
| Candidate rejection tombstone | Rejected candidates get durable tombstone rows | `tests/test_memory.py` |
| Page tombstone | Page status becomes `tombstoned:<reason>` and active recall omits it | `tests/test_memory.py` |
| Memory health report | Counts, coverage, score, and review cards stay compact | `tests/test_memory.py` |
| CLI query debug | `--debug-query` includes query plan metadata while default JSON omits it | `tests/test_cli.py` |
| CLI health and tombstones | Health, tombstone, and tombstone listing commands normalize output/errors | `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: use links to preserve why memory changed.
- Good: store scanner output as compact evidence on the candidate instead of adding a separate workflow.
- Good: use one-hop page links to surface adjacent wiki knowledge while keeping tool schemas unchanged.
- Good: require explicit `search_scope="sessions"` for raw-session recall so default memory search stays lightweight.
- Good: expose query plans as compact metadata so the model can decide whether to refine, read, or ask the user.
- Good: expose health cards as compact model input so the model chooses whether to verify, link, archive, or ignore.
- Base: deterministic dream logic may emit signals that later model decisions consume.
- Base: deterministic QueryPlanner is a retrieval helper, not a mandatory pre-run workflow.
- Bad: overwrite an active memory page directly from a conflicting candidate.
- Bad: bypass `MemoryEngine.write_candidate()` from tools or W0 ingestion.
- Bad: hide reinforcement or conflict decisions without a memory link.
- Bad: treat advisory tombstone annotations as durable deletion records.
- Bad: let tombstoned stable pages remain in active recall or L1 snapshots.

### 6. Tests Required
- Promotion creates page, updates candidate status, and creates `promoted_to`.
- W0 ingestion creates candidates from model-marked working notes and skips ephemeral notes.
- Candidate writes cover trusted/low-risk and injected/high-risk safety scans.
- CLI `memory notes` covers default open notes, unfiltered notes, metadata/result payloads, and compact non-JSON rows.
- Duplicate reinforcement updates confidence and creates `reinforces`.
- Conflict review creates `conflicts_with` and leaves the active page unchanged.
- Search/context cards remain compact and omit raw evidence.
- Associative recall covers direct links, backlinks, archived-page filtering, and compact context cards.
- L4 session search covers explicit session scope, compact context cards, and omission of raw message content.
- QueryPlanner covers lexical/dimension/temporal route generation, fused retrieval annotations, and CLI debug output.
- Durable tombstones cover candidate rejection, explicit page tombstone, filtered tombstone listing, and compact read payloads.
- Memory health covers counts, coverage, review cards, compact tool evidence, and CLI output.
- `memory_read` covers both candidates and stable pages.
- CLI `memory list` covers default draft candidates, active pages, unfiltered all inventory, and compact non-JSON rows.
- CLI `memory read` covers candidates, pages, non-JSON output, and missing ids.
- CLI `memory links` covers outgoing-only, incoming-only, both directions, and compact non-JSON rows.
- CLI `memory snapshot` covers missing snapshots, loaded snapshots, and compact non-JSON rows.
- L1 snapshot compile/load behavior is covered, including invalid files.
- Harness suite for memory safety covers candidate-first writes, conflict guardrails, compact prompt payloads, duplicate reinforcement, and prompt-injection scanner gating.

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
