# Hook Guidelines

## Scenario: Browser Helpers Instead Of Framework Hooks

### 1. Scope / Trigger
- Trigger: adding browser stateful behavior, data fetching, stream reading, or event listeners in `app.js`.
- Goal: keep frontend logic small and explicit without introducing framework-style hooks.

### 2. Current Pattern
- There are no React/Vue/Svelte hooks in this project.
- Stateful browser logic lives in the single `state` object in `app.js`.
- Side effects are plain functions: `runTurn`, `resumeLastRun`, `readNdjson`, `handleEvent`, and renderer helpers.
- Event listeners are registered once near the top of `app.js`.

### 3. Contracts
- New state fields must be initialized in the top-level `state` object.
- Browser persistence keys must be documented in `state-management.md`.
- Fetch helpers should return early on failed responses and avoid throwing into the global event loop.
- Stream parsing should stay centralized in `readNdjson`.
- Resume/de-duplication must flow through `handleEvent`; do not mutate the timeline from replay paths directly.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| New persistence key | Documented and reset by the reset handler | `tests/test_web.py` asset assertion |
| New fetch helper | Handles non-OK response without breaking chat state | Web tests or manual check |
| New event type | Routed through `handleEvent` and de-duplicated | Asset/projection tests |

### 5. Good/Base/Bad Cases
- Good: add `state.someCache = new Map()` and clear it in reset when durable state changes.
- Good: keep online/replay behavior calling `resumeLastRun()`.
- Base: small pure formatting helpers can remain near render functions.
- Bad: adding a frontend framework solely to get hooks.
- Bad: bypassing `handleEvent` for replayed events.

### 6. Tests Required
- Asset tests should assert critical persistence keys and event-routing names.
- API tests should cover any new backend route used by a fetch helper.
