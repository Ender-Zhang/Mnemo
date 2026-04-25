# Memory Engine Contracts

## Scenario: Candidate Consolidation Signals

### 1. Scope / Trigger
- Trigger: changes to `mnemo/memory/engine.py`, memory storage APIs, dream consolidation, or memory tool handlers.
- Goal: preserve candidate-first learning while producing explicit provenance signals for reinforcement and conflicts.

### 2. Signatures
- `MemoryEngine.search(query: str, limit: int = 5) -> list[dict[str, Any]]`
- `MemoryEngine.context_cards(query: str, limit: int = 5) -> list[dict[str, Any]]`
- `MemoryEngine.ingest_working_notes(limit: int = 20) -> dict[str, Any]`
- `MemoryEngine.promote_candidate(candidate_id: str) -> dict[str, Any]`
- `MemoryEngine.reject_candidate(candidate_id: str, reason: str) -> dict[str, Any]`
- `MemoryEngine.dream_consolidate(limit: int = 20, min_confidence: float = 0.7) -> dict[str, Any]`
- `MemoryEngine.compile_l1_snapshot(limit: int = 50) -> dict[str, Any]`
- `MemoryEngine.load_l1_snapshot() -> dict[str, Any] | None`
- `EvalHarness.run_suite("memory-safety") -> SuiteReport`
- CLI: `mnemo harness eval memory-safety --json`
- `StateStore.update_memory_page_confidence(page_id: str, confidence: float) -> None`
- `StateStore.list_memory_pages(status: str | None = "active", limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.list_memory_backlinks(target_id: str) -> list[dict[str, Any]]`
- `StateStore.add_working_note(mission_id: str, run_id: str, content: str, *, metadata: dict[str, Any] | None = None) -> str`
- `StateStore.list_working_notes(status: str | None = "open", limit: int = 50) -> list[dict[str, Any]]`
- `StateStore.update_working_note_status(note_id: str, status: str, *, result: dict[str, Any] | None = None) -> None`

### 3. Contracts
- Normal tools write memory candidates, not stable pages.
- Stable memory pages are created through promotion or explicit curation.
- W0 working notes are mission-scoped scratchpad entries.
- DreamCycle only turns W0 notes into memory candidates when the note metadata has `retention="memory_candidate"`.
- W0 ingestion creates draft candidates and marks source notes as `candidate_created`; it never writes stable memory pages directly.
- W0 notes without durable retention are marked `skipped:ephemeral`; short notes are marked `skipped:too_short`.
- Duplicate candidates are rejected as `rejected:duplicate`.
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
- `memory_read` must read stable memory pages as well as memory candidates.
- The `memory-safety` eval suite must remain deterministic and local.
- The `memory-safety` eval suite covers candidate-first writes, conflict guardrails, compact prompt payloads, and duplicate reinforcement.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Empty candidate | `rejected:empty` | `tests/test_memory.py` |
| Exact duplicate of active page | Reject candidate, raise page confidence, add `reinforces` link | `tests/test_memory.py` |
| Obvious contradiction | Mark `needs_review:conflict`, add `conflicts_with` link, do not promote | `tests/test_memory.py` |
| Low confidence non-conflict | Keep `draft`, return skipped entry | `tests/test_memory.py` |
| High confidence non-conflict | Promote to active memory page | `tests/test_memory.py` |
| W0 note with memory retention | Create candidate, mark note `candidate_created`, continue normal consolidation | `tests/test_memory.py` |
| W0 note without memory retention | Mark note `skipped:ephemeral`, create no candidate | `tests/test_memory.py` |
| Missing or invalid snapshot file | Return `None` | `tests/test_memory.py` |
| Active and archived pages | Snapshot includes active pages only | `tests/test_memory.py` |
| Direct association | Search returns linked active pages that do not match the query text | `tests/test_memory.py` |
| Reverse association | Search returns active pages linked back to the query match | `tests/test_memory.py` |
| Association cards | Context cards include relation metadata without full raw payloads | `tests/test_memory.py` |
| Memory page read | `memory_read` can load stable pages by id | `tests/test_tools.py` |
| Memory safety eval suite | `harness eval memory-safety --json` passes with deterministic local cases | `tests/test_harness.py`, `tests/test_cli.py` |

### 5. Good/Base/Bad Cases
- Good: use links to preserve why memory changed.
- Good: use one-hop page links to surface adjacent wiki knowledge while keeping tool schemas unchanged.
- Base: deterministic dream logic may emit signals that later model decisions consume.
- Bad: overwrite an active memory page directly from a conflicting candidate.
- Bad: hide reinforcement or conflict decisions without a memory link.

### 6. Tests Required
- Promotion creates page, updates candidate status, and creates `promoted_to`.
- W0 ingestion creates candidates from model-marked working notes and skips ephemeral notes.
- Duplicate reinforcement updates confidence and creates `reinforces`.
- Conflict review creates `conflicts_with` and leaves the active page unchanged.
- Search/context cards remain compact and omit raw evidence.
- Associative recall covers direct links, backlinks, archived-page filtering, and compact context cards.
- `memory_read` covers both candidates and stable pages.
- L1 snapshot compile/load behavior is covered, including invalid files.
- Harness suite for memory safety covers candidate-first writes, conflict guardrails, compact prompt payloads, and duplicate reinforcement.

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
