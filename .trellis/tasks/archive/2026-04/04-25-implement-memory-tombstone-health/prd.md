# Implement Memory Tombstone Health Foundation

## Goal
Add the first durable memory forgetting and health layer so Mnemo can keep rejected or outdated memory from re-entering active recall while exposing compact health signals to the model and human operator.

## Requirements
- Persist memory tombstones for stable pages and rejected candidates.
- Exclude tombstoned pages from active recall and surface tombstone metadata through explicit read paths.
- Provide a compact memory health report with counts and review cards.
- Expose tombstone and health operations through provider-native tools and CLI commands.
- Keep the implementation lightweight and model-directed; do not add a fixed maintenance workflow.

## Acceptance Criteria
- [x] Storage initializes and round-trips tombstone records idempotently.
- [x] MemoryEngine can tombstone stable pages and candidates with normalized errors for missing ids.
- [x] Search and L1 snapshot behavior continue to omit tombstoned pages by default.
- [x] `memory_health_report` and `memory_tombstone` tools return compact summaries/evidence.
- [x] CLI can inspect health and create/list tombstones with JSON and non-JSON output.
- [x] Relevant backend specs and implementation checklist are updated.
- [x] Targeted and full test suites pass.

## Technical Notes
- Schema changes belong in `StateStore.initialize()` migrations.
- Normal task tools still write candidates first; tombstone is an explicit curation/action tool.
- Health report is advisory input for model decisions, not an automatic scheduler.
