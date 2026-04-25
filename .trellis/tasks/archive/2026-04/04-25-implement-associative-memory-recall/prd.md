# Implement Associative Memory Recall

## Goal

Turn the existing memory link table into useful LLM Wiki style recall without adding a workflow router: when the model searches memory, directly linked active pages should be surfaced as compact associated memories.

## Scope

- Add reverse memory-link lookup in storage.
- Expand `MemoryEngine.search()` with one-hop linked active pages from direct and reverse links.
- Keep associative results deterministic, bounded, and de-duplicated.
- Keep prompt context cards compact and body-safe.
- Make `memory_read` honor its contract by reading stable pages as well as candidates.
- Cover memory engine, tool, and CLI behavior with tests.
- Update memory spec and implementation checklist.

## Acceptance

- [x] Searching a page returns directly linked active pages even when linked page content does not match the query.
- [x] Reverse links also surface associated active pages.
- [x] Associated pages include relation/source metadata and do not duplicate seed page ids.
- [x] Context cards include compact association metadata and omit raw evidence.
- [x] `memory_read` can read a stable memory page by id.
- [x] Focused and full unit suites pass.
- [x] Changes are committed locally.
