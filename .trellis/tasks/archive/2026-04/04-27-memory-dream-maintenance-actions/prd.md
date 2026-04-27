# Memory Dream Maintenance Actions

## Goal
Close the memory self-evolution gap by letting DreamCycle apply compact, model-proposed memory maintenance actions through existing MemoryEngine primitives, without adding a fixed workflow router.

## Requirements
- Reuse the existing DreamCycle report and MemoryEngine maintenance APIs.
- Add a compact action executor for dream memory plans that supports safe memory maintenance actions only.
- Supported actions should cover the current checklist gap: stale/low-value archival, harmful tombstone eval routing, and replacement links when a replacement is explicitly supplied.
- Actions must be bounded, auditable, and compact: no full raw transcript or memory body should be copied into action summaries.
- CLI and tests should expose the action results through existing dream report flows.
- Keep the model-led design: the runtime provides tools/capabilities and applies explicit action proposals, not a hard-coded workflow.
- Update design docs, specs, and checklist.

## Acceptance Criteria
- [x] DreamCycle accepts maintenance actions in a provider/model plan and applies valid memory actions.
- [x] Invalid or unsupported dream actions are skipped with compact error metadata, not Python tracebacks.
- [x] Harmful dream tombstone actions create compact draft memory-core eval cases when a run source is available.
- [x] Low-usefulness actions archive memories through existing tombstone semantics.
- [x] Dream reports persist compact applied/skipped action results.
- [x] Tests cover MemoryEngine/DreamCycle, CLI report output, and checklist/spec alignment.

## Technical Notes
- No database migration is expected; reports can store compact action results in existing JSON payloads.
- Prefer existing tombstone, health, decay, and eval-case APIs over new data models.
- Provider-led scheduling can remain future work; this task focuses on applying memory maintenance decisions once a dream plan exists.
