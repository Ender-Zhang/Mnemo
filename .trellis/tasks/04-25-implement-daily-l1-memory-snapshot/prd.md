# Implement Daily L1 Memory Snapshot

## Goal
Compile stable memory pages into a compact daily L1 snapshot that can be injected into prompts as cache-friendly context, while keeping detailed recall under model-controlled `memory_search` / `memory_read` tool calls.

## Requirements
- Add a storage API to list active memory pages without exposing raw evidence.
- Add `MemoryEngine` APIs to compile and load an L1 memory snapshot.
- Generate the snapshot during dream consolidation.
- Inject the snapshot into prompt assembly as an optional daily-cache block before turn-scoped memory cards.
- Load the snapshot in local and provider runtimes without adding workflow routing.
- Keep snapshot content compact and metadata safe.
- Update tests, implementation checklist, and backend specs.

## Acceptance Criteria
- [x] `compile_l1_snapshot()` writes a JSON snapshot under Mnemo state.
- [x] `load_l1_snapshot()` returns `None` when missing or invalid and a dict when present.
- [x] Dream consolidation returns snapshot metadata after processing candidates.
- [x] Prompt assembly includes a droppable `memory.l1_snapshot` block only when snapshot items exist.
- [x] Local/provider runtimes pass the loaded snapshot into prompt assembly.
- [x] Focused and full unit test suites pass.
- [ ] Git is committed and pushed.

## Technical Notes
- The snapshot is not a workflow step. It is a compact memory affordance in the prompt.
- Detailed memory access remains available through provider-native tool calls.
- Snapshot blocks should use stable ordering and daily cache policy to improve KV-cache reuse.
