# Type Safety

## Scenario: Runtime Shape Guards In Plain JavaScript

### 1. Scope / Trigger
- Trigger: changes to browser event handling, JSON API payloads, or stream parsing in `app.js`.
- Goal: keep plain JavaScript robust without adding a compile step.

### 2. Current Type Boundary
- Backend shapes are Python dataclasses and JSON dicts: `ChatEvent`, `RunRequest`, artifact payloads, and replay responses.
- Browser code treats all JSON as untrusted and uses optional chaining/fallbacks when reading fields.
- Event routing is discriminated by `event.type`.
- The browser never relies on internal SQLite sequence numbers.

### 3. Contracts
- Parse NDJSON only in `readNdjson`; malformed lines should surface as error cards from the caller path.
- Use optional chaining for nested event data: `event.data?.artifact`.
- Use default strings for missing UI text.
- IDs persisted in `localStorage` must be strings.
- Collections should use `Set`/`Map` when uniqueness or caching matters.
- Dynamic content must be written through DOM text APIs.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Missing optional event data | Renderer falls back instead of crashing | Asset/manual check |
| Duplicate event id | Set membership prevents double render | `tests/test_web.py` |
| Unknown event type | Ignored by default route | Asset review |
| Artifact cache | Map stores loaded artifacts for the session | `tests/test_web.py` asset assertion |

### 5. Good/Base/Bad Cases
- Good: `const title = artifact?.title || "Artifact";`.
- Good: `state.renderedEventIds = new Set()`.
- Base: use JSDoc only when a helper's payload shape is not obvious.
- Bad: assuming `event.data.artifact.title` always exists.
- Bad: using numeric run-event `seq` as frontend continuation state.

### 6. Tests Required
- Add `tests/test_web.py` assertions for new persisted keys, caches, or API fields.
- Backend tests should assert JSON payload shape before frontend code depends on it.
