# Memory Harmful Eval Routing

## Goal
Finish the harmful branch of selective forgetting by routing harmful memory tombstones into compact eval-case proposals, while keeping the model-led tool surface and avoiding a new workflow router.

## Requirements
- Reuse `MemoryEngine.tombstone_memory()` and `memory_tombstone` instead of adding a new maintenance workflow.
- `reason=harmful` should keep the existing tombstone semantics and also create a compact draft eval case when a source run is available.
- ToolHarness should pass the current run id so harmful page/candidate curation can create an eval case even when the page has no source candidate.
- CLI should optionally accept an eval run id for harmful tombstones and normalize missing run errors.
- Eval case payloads must be compact and must not include full memory bodies or raw transcripts.
- Specs, design docs, and checklist should reflect the new routing.

## Acceptance Criteria
- [x] Harmful candidate tombstone creates a draft eval case using the candidate source run.
- [x] Harmful page tombstone can create a draft eval case using `eval_run_id` or ToolHarness context run id.
- [x] Non-harmful tombstones do not create eval cases.
- [x] Tool compact evidence includes only compact eval case metadata.
- [x] CLI JSON/plain output exposes compact eval case metadata and missing eval run ids are normalized.
- [x] Tests, design docs, specs, and checklist are updated.

## Technical Notes
- `StateStore.add_eval_case()` already exists and should be reused.
- No schema migration is expected.
- This is a routing side effect of an explicit model/user curation action, not an always-on background workflow.
