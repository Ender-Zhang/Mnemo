# Implement W0 Working Memory Candidate Pipeline

## Goal
Connect mission-scoped working notes to the memory evolution loop so useful W0 observations can become long-term memory candidates during DreamCycle without adding a rigid workflow router.

## Requirements
- Add storage APIs to list working notes and mark them processed.
- Add a `MemoryEngine.ingest_working_notes()` step that converts model-marked working notes into draft memory candidates.
- Preserve existing candidate-first memory policy: working notes must not write stable memory pages directly.
- Include created/skipped counts in DreamCycle output.
- Keep the pipeline lightweight and deterministic; the model can still write richer candidates directly through `memory_write_candidate`.
- Update CLI output, specs, tests, and implementation checklist.

## Acceptance Criteria
- [x] Working notes can be listed by processed state.
- [x] DreamCycle turns durable working notes into draft memory candidates with evidence.
- [x] Empty/short working notes are marked processed with a skip reason.
- [x] DreamCycle then reuses the existing candidate promotion/conflict/snapshot path.
- [x] Focused and full tests pass.
- [ ] Git is committed and pushed.

## Technical Notes
- This is W0-to-candidate ingestion, not direct stable memory mutation.
- The ingestion layer should be small: model-marked notes in, candidate drafts out, existing MemoryEngine handles consolidation.
