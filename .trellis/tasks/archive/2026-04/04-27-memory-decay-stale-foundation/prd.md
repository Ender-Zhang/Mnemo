# Memory Decay And Stale Review Foundation

## Goal
Implement a lightweight memory maintenance primitive that lets the model see and act on stale or expired memory without adding a fixed workflow.

## Requirements
- Add a memory-engine API that inspects active memory pages for metadata-driven decay and expiration.
- Mark expired or sufficiently decayed active pages as stale so recall and L1 snapshots exclude them.
- Return compact review cards so the model can decide whether to verify, resurrect, tombstone, or ignore.
- Expose the primitive through a CLI command for harness and manual inspection.
- Keep behavior deterministic, bounded, and dependency-free.

## Acceptance Criteria
- [x] Active pages with expired `metadata.expires` become stale.
- [x] Active pages with overdue `metadata.decay_days` have confidence reduced and become stale below the threshold.
- [x] Fresh active pages remain active and unchanged.
- [x] L1 snapshot compilation excludes stale pages through the existing active-page filter.
- [x] CLI JSON and text output are compact and normalized.
- [x] Tests cover engine behavior and CLI behavior.

## Technical Notes
- This is not a scheduler or workflow. It is a model-callable maintenance capability.
- Use existing `StateStore` memory page APIs; avoid schema changes unless strictly necessary.
- Keep prompt-facing/report payloads compact and raw-evidence-free.
