# Implement Recall Cards

## Goal

Let the model recall past work, artifacts, decisions, and knowledge from the normal tool loop, then show compact actionable result cards in the existing single chat surface.

## Requirements

- Add a provider-native read-only recall tool; do not add a dashboard or rule-based workflow.
- Return compact result cards only: ids, titles, summaries, provenance, and small action hints.
- Search existing memory/session messages, artifacts, inbox decisions, and run history without schema changes.
- Project successful recall tool results into a `recall.card` chat event.
- Render recall cards inline in the web timeline with safe text handling and lightweight actions.
- Preserve existing artifact body loading, decision resolution, replay, and streaming contracts.

## Acceptance Criteria

- [x] `recall_search` is exposed through `ToolRegistry.specs()`.
- [x] `recall_search` returns compact `past_work`, `artifact`, `decision`, and `knowledge` items when matching state exists.
- [x] `recall_search` compact evidence omits artifact bodies and raw session transcripts.
- [x] Local deterministic runtime supports a `recall:` trigger for harness/tests.
- [x] Runtime projection emits `recall.card` for successful recall results.
- [x] Web frontend renders recall cards inline and exposes basic continue/use/open/decision actions.
- [x] Tests cover tool behavior, local runtime projection, web asset hooks, and checklist/spec alignment.

## Technical Notes

- The data flow is: provider/native tool call -> ToolHarness -> compact recall result -> `recall.card` projection -> inline frontend rendering.
- This is intentionally a model-selected capability; user-visible recall still happens from one chat box.
- Action buttons may prefill the composer or reuse existing artifact/decision APIs; deeper artifact editing and run continuation remain later work.
