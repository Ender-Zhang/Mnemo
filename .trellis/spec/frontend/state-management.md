# State Management

> How state is managed in this project.

## Scenario: Single-Chat Event Resume

### 1. Scope / Trigger
- Trigger: changes to `mnemo/interfaces/web.py`, `mnemo/interfaces/web_assets/app.js`, `ChatEvent` replay, or browser persistence keys.
- Goal: keep the user-facing single chat resumable across reloads and reconnects without exposing internal ledger sequence numbers to the browser.

### 2. Signatures
- Browser key: `mnemo.conversation_id`
- Browser key: `mnemo.mission_id`
- Browser key: `mnemo.last_run_id`
- Browser key: `mnemo.last_event_id`
- Runtime state: `state.activeRunId: string`
- Runtime state: `state.renderedEventIds: Set<string>`
- Runtime state: `state.artifacts: Map<string, object>`
- API: `GET /api/events?run_id=<run_id>&chat=1`
- API: `GET /api/events?run_id=<run_id>&chat=1&sinceEventId=<event_id>`
- API: `GET /api/artifacts?artifact_id=<artifact_id>`
- API: `POST /api/runs/cancel` with JSON `{ "run_id": string, "reason"?: string }`
- API: `GET /api/inbox?status=open|resolved|all&priority=critical|high|normal|low`
- API: `POST /api/inbox/resolve` with JSON `{ "item_id": string, "resolution": "accepted"|"rejected"|"ignored", "notes"?: string }`
- API: `POST /api/learning/memory` with JSON `{ "candidate_id": string, "action": "accept"|"this_time"|"reject" }`

### 3. Contracts
- The browser stores durable conversation, mission, last run, and last processed chat event ids in `localStorage`.
- `last_event_id` is always a `ChatEvent.event_id`, not a SQLite `run_events.seq`.
- On page load, the web client replays the last run if `mnemo.last_run_id` exists.
- When the visible timeline is empty, replay fetches all chat events for the last run.
- Incremental resume uses `sinceEventId` and appends only later events.
- The client must de-duplicate events by `event_id` before mutating the timeline.
- Reset clears all persisted chat continuity keys and the rendered-event set.
- Reset is disabled and guarded while `state.busy` is true; active turns should use Stop instead.
- Artifact cards render from streamed metadata and fetch artifact body content only when opened.
- Loaded artifacts are cached in `state.artifacts` for the current browser session.
- Decision cards resolve persisted Inbox items by id and keep status local to the card.
- Learning chips resolve persisted memory candidates by id and keep status local to the card.
- While a run is streaming, the composer exposes one stop control that calls `/api/runs/cancel`.
- `activeRunId` is a volatile current-stream id and must not be stored in `localStorage`.
- Stop/cancel requests use `activeRunId`; `lastRunId` remains the durable replay/resume id.
- The stop control stays disabled until the current stream emits its first `run_id`.
- The stop control must not clear conversation, mission, last run, or last event state.
- After requesting cancellation, the browser keeps reading the active NDJSON stream until completion/error so it can receive the final event.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Full replay | Returns chat events from `turn.started` onward | `tests/test_web.py` |
| `sinceEventId` matches | Returns only later chat events | `tests/test_web.py` |
| `sinceEventId` missing | Returns all chat events for safe rehydrate | `tests/test_web.py` |
| Client asset | Contains `mnemo.last_event_id`, `sinceEventId`, and `renderedEventIds` handling | `tests/test_web.py` |
| Artifact fetch | Returns stored artifact body by id and rejects missing/unknown ids | `tests/test_web.py` |
| Artifact viewer asset | Contains on-demand artifact fetch and body rendering hooks | `tests/test_web.py` |
| Inbox decision resolve | Resolves a persisted decision item and returns JSON errors for missing/invalid input | `tests/test_web.py` |
| Learning memory action | Promotes or rejects a persisted memory candidate and returns JSON errors for missing/invalid input | `tests/test_web.py` |
| Stop control | Requests run cancellation with active run id without clearing replay state | `tests/test_web.py` |
| Busy reset | Reset is disabled/guarded while a stream is active | `tests/test_web.py` |

### 5. Good/Base/Bad Cases
- Good: persist `event.event_id` after each processed chat event and use `sinceEventId` for incremental resume.
- Good: fetch artifact body via `/api/artifacts` after the user opens an artifact card.
- Good: resolve decision cards by item id through `/api/inbox/resolve`, leaving conversation replay keys untouched.
- Good: resolve learning chips by candidate id through `/api/learning/memory`, leaving conversation replay keys untouched.
- Good: request cancellation and keep the stream open until the runtime emits completion.
- Good: clear `activeRunId` before each new turn so a stale replay id cannot be cancelled.
- Good: keep reset as an idle-only operation; use Stop for active run interruption.
- Base: sequence-based `since` remains available for CLI/debug callers.
- Bad: store ledger seq as frontend resume state.
- Bad: append replayed events without event-id de-duplication.
- Bad: put full artifact bodies in every `artifact.card` event.
- Bad: abort the active stream immediately after requesting cancellation and miss the final `run.completed`.
- Bad: send cancellation with `lastRunId` while a new stream is still waiting for its first event.
- Bad: clearing localStorage/timeline while a stream is still appending events.

### 6. Tests Required
- Web replay API supports full replay and `sinceEventId`.
- Unknown `sinceEventId` returns a safe full replay.
- Frontend asset includes resume persistence and de-duplication logic.
- Artifact API covers success, missing id, and unknown id.
- Frontend asset includes on-demand artifact body loading.
- Inbox API covers listing and resolution, including missing and invalid resolution errors.
- Frontend asset includes inline decision resolution hooks.
- Learning memory API covers accept, this-turn-only, reject, missing candidate, and invalid action errors.
- Frontend asset includes inline learning resolution hooks.
- Run cancel API covers success, missing id, unknown id, and frontend stop-control asset hooks.

### 7. Wrong vs Correct
#### Wrong
```javascript
localStorage.setItem("mnemo.last_event_id", String(runEventSeq));
```

#### Correct
```javascript
localStorage.setItem("mnemo.last_event_id", event.event_id);
```
