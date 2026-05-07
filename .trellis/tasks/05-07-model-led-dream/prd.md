# Model-Led Dream Maintenance

## Goal
Make DreamCycle maintenance model-led instead of deterministic fallback driven.

## Requirements
- Dream maintenance must collect bounded deltas and expose a constrained tool surface to the model.
- Dream must not automatically promote, reject, or consolidate draft memory candidates without explicit model-selected actions.
- Manual `--actions-json` remains available as an audited model-action injection path for tests and offline use.
- Candidate promotion from Dream must happen through an explicit maintenance tool and still pass safety/quality/conflict validation.
- Scheduler and CLI surfaces must preserve compact reports and avoid leaking provider secrets.

## Acceptance Criteria
- [ ] `mnemo dream run` with no provider/actions records a no-action/model-required report instead of local fallback consolidation.
- [ ] Provider-backed Dream can execute model tool calls and persist a Dream report.
- [ ] Scheduled Dream ticks no longer run deterministic candidate promotion by default.
- [ ] Existing Dream action handling remains compact and supports model-selected promotion/rejection.
- [ ] Unit tests cover no-fallback behavior and model-led tool execution.

## Technical Notes
- Keep `MemoryEngine` as the memory facade; put provider loop code under `mnemo/runtime/`.
- Tool execution should use existing `ToolHarness`, `ToolRegistry`, provider-native tool calls, and compact results.
- Update design/spec docs where current text still describes deterministic fallback.
