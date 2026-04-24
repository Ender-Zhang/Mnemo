# Memory Engine Contracts

## Scenario: Candidate Consolidation Signals

### 1. Scope / Trigger
- Trigger: changes to `mnemo/memory/engine.py`, memory storage APIs, dream consolidation, or memory tool handlers.
- Goal: preserve candidate-first learning while producing explicit provenance signals for reinforcement and conflicts.

### 2. Signatures
- `MemoryEngine.search(query: str, limit: int = 5) -> list[dict[str, Any]]`
- `MemoryEngine.context_cards(query: str, limit: int = 5) -> list[dict[str, Any]]`
- `MemoryEngine.promote_candidate(candidate_id: str) -> dict[str, Any]`
- `MemoryEngine.reject_candidate(candidate_id: str, reason: str) -> dict[str, Any]`
- `MemoryEngine.dream_consolidate(limit: int = 20, min_confidence: float = 0.7) -> dict[str, Any]`
- `MemoryEngine.compile_l1_snapshot(limit: int = 50) -> dict[str, Any]`
- `MemoryEngine.load_l1_snapshot() -> dict[str, Any] | None`
- `StateStore.update_memory_page_confidence(page_id: str, confidence: float) -> None`
- `StateStore.list_memory_pages(status: str | None = "active", limit: int = 50) -> list[dict[str, Any]]`

### 3. Contracts
- Normal tools write memory candidates, not stable pages.
- Stable memory pages are created through promotion or explicit curation.
- Duplicate candidates are rejected as `rejected:duplicate`.
- Duplicate candidates may reinforce existing page confidence and must create a `reinforces` memory link.
- Conflicting candidates are not promoted automatically.
- Conflicting candidates are marked `needs_review:conflict` and linked with `conflicts_with`.
- Dream consolidation returns `promoted`, `rejected`, `skipped`, `conflicts`, and a compact L1 `snapshot`.
- L1 snapshots contain active memory page cards only: `id`, `title`, `summary`, `scope`, `confidence`, and `updated_at`.
- L1 snapshots are stored at `wiki/l1-memory-snapshot.json`.
- Prompt-facing snapshots must omit raw evidence and full page content.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Empty candidate | `rejected:empty` | `tests/test_memory.py` |
| Exact duplicate of active page | Reject candidate, raise page confidence, add `reinforces` link | `tests/test_memory.py` |
| Obvious contradiction | Mark `needs_review:conflict`, add `conflicts_with` link, do not promote | `tests/test_memory.py` |
| Low confidence non-conflict | Keep `draft`, return skipped entry | `tests/test_memory.py` |
| High confidence non-conflict | Promote to active memory page | `tests/test_memory.py` |
| Missing or invalid snapshot file | Return `None` | `tests/test_memory.py` |
| Active and archived pages | Snapshot includes active pages only | `tests/test_memory.py` |

### 5. Good/Base/Bad Cases
- Good: use links to preserve why memory changed.
- Base: deterministic dream logic may emit signals that later model decisions consume.
- Bad: overwrite an active memory page directly from a conflicting candidate.
- Bad: hide reinforcement or conflict decisions without a memory link.

### 6. Tests Required
- Promotion creates page, updates candidate status, and creates `promoted_to`.
- Duplicate reinforcement updates confidence and creates `reinforces`.
- Conflict review creates `conflicts_with` and leaves the active page unchanged.
- Search/context cards remain compact and omit raw evidence.
- L1 snapshot compile/load behavior is covered, including invalid files.

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
