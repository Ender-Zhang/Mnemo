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
- Runtime state: `state.renderedEventIds: Set<string>`
- API: `GET /api/events?run_id=<run_id>&chat=1`
- API: `GET /api/events?run_id=<run_id>&chat=1&sinceEventId=<event_id>`

### 3. Contracts
- The browser stores durable conversation, mission, last run, and last processed chat event ids in `localStorage`.
- `last_event_id` is always a `ChatEvent.event_id`, not a SQLite `run_events.seq`.
- On page load, the web client replays the last run if `mnemo.last_run_id` exists.
- When the visible timeline is empty, replay fetches all chat events for the last run.
- Incremental resume uses `sinceEventId` and appends only later events.
- The client must de-duplicate events by `event_id` before mutating the timeline.
- Reset clears all persisted chat continuity keys and the rendered-event set.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Full replay | Returns chat events from `turn.started` onward | `tests/test_web.py` |
| `sinceEventId` matches | Returns only later chat events | `tests/test_web.py` |
| `sinceEventId` missing | Returns all chat events for safe rehydrate | `tests/test_web.py` |
| Client asset | Contains `mnemo.last_event_id`, `sinceEventId`, and `renderedEventIds` handling | `tests/test_web.py` |

### 5. Good/Base/Bad Cases
- Good: persist `event.event_id` after each processed chat event and use `sinceEventId` for incremental resume.
- Base: sequence-based `since` remains available for CLI/debug callers.
- Bad: store ledger seq as frontend resume state.
- Bad: append replayed events without event-id de-duplication.

### 6. Tests Required
- Web replay API supports full replay and `sinceEventId`.
- Unknown `sinceEventId` returns a safe full replay.
- Frontend asset includes resume persistence and de-duplication logic.

### 7. Wrong vs Correct
#### Wrong
```javascript
localStorage.setItem("mnemo.last_event_id", String(runEventSeq));
```

#### Correct
```javascript
localStorage.setItem("mnemo.last_event_id", event.event_id);
```
