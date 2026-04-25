# Dream Maintenance Interface

## Goal
Make DreamCycle inspectable and delta-oriented without turning memory maintenance into a fixed workflow.

## Requirements
- Add a compact Dream delta that captures only pending W0 notes, recent draft/review candidates, changed pages, tombstones, recent runs, and health cards.
- Add a Dream report shape that records the model decision surface, local execution fallback, and post-run memory health.
- Keep existing deterministic consolidation as the local fallback path, but restrict it to collected delta when possible.
- Add CLI commands for running Dream now, inspecting status, and reading the latest report.
- Keep reports compact and persisted in managed state without adding an unnecessary database surface.

## Acceptance Criteria
- [x] `mnemo dream run --json` returns `delta`, `plan`, `execution`, and `health_after`.
- [x] `mnemo dream --now --json` aliases the run path.
- [x] `mnemo dream status --json` reports latest Dream report metadata and backlog counts.
- [x] `mnemo dream report --latest --json` returns the latest persisted report.
- [x] Dream consolidation can limit candidate processing to a delta candidate set while preserving existing behavior when no set is provided.
- [x] Memory and CLI tests cover report persistence, status, latest report, and delta-limited consolidation.

## Technical Notes
- Reports live under `runs/dream-reports/` so backup/export already includes them.
- The plan is a model-facing decision contract, not a hard-coded workflow. Local execution remains a fallback until provider-led Dream runs are wired into daemon idle scheduling.
