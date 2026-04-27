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
- Browser key: `mnemo.last_user_intent`
- Runtime state: `state.activeRunId: string`
- Runtime state: `state.renderedEventIds: Set<string>`
- Runtime state: `state.activityRows: Map<string, ActivityRow>`
- Runtime state: `state.artifacts: Map<string, object>`
- Runtime state: `state.artifactRelated: Map<string, object[]>`
- Runtime state: `state.settings: object | null`
- Runtime state: `state.lastUserIntent: string`
- UI event: `recall.card` with `{ recall: { query: string, scope: string, count: number, items: RecallItem[] } }`
- UI event: `learning.chip` with `{ item: { item_id: string, kind: string, status: string, summary: string, requires_confirmation?: boolean, risk?: string, confirmation_reason?: string } }`
- API: `GET /api/events?run_id=<run_id>&chat=1`
- API: `GET /api/events?run_id=<run_id>&chat=1&sinceEventId=<event_id>`
- API: `GET /api/artifacts?artifact_id=<artifact_id>` returns `{ "artifact": ArtifactWithBody, "related": ArtifactMetadata[] }`
- API: `POST /api/runs/cancel` with JSON `{ "run_id": string, "reason"?: string }`
- API: `GET /api/inbox?status=open|resolved|all&priority=critical|high|normal|low`
- API: `POST /api/inbox/resolve` with JSON `{ "item_id": string, "resolution": "accepted"|"rejected"|"ignored", "notes"?: string }`
- API response: accepted tool approvals may include compact `{ "tool_result": { "tool": string, "ok": boolean, "summary": string } }`.
- API: `POST /api/learning/memory` with JSON `{ "candidate_id": string, "action": "accept"|"this_time"|"reject"|"undo" }`
- API: `GET /api/settings`
- API: `POST /api/settings` with JSON `{ "quiet_hours": { "enabled": boolean, "start": "HH:MM", "end": "HH:MM", "timezone"?: string } }`

### 3. Contracts
- The browser stores durable conversation, mission, last run, and last processed chat event ids in `localStorage`.
- `last_event_id` is always a `ChatEvent.event_id`, not a SQLite `run_events.seq`.
- On page load, the web client replays the last run if `mnemo.last_run_id` exists.
- When the visible timeline is empty, replay fetches all chat events for the last run.
- Incremental resume uses `sinceEventId` and appends only later events.
- The client must de-duplicate events by `event_id` before mutating the timeline.
- `turn.started` replay should restore the user prompt into the timeline when the client is not busy.
- `mnemo.last_user_intent` stores only a compact recent prompt summary for the browser-local context panel.
- Right-panel activity rows are volatile browser state and must be rebuilt from stream/replay events, not stored in `localStorage`.
- Reset clears all persisted chat continuity keys and the rendered-event set.
- Reset is disabled and guarded while `state.busy` is true; active turns should use Stop instead.
- Artifact cards render from streamed metadata and fetch artifact body content only when opened.
- Artifact action buttons reuse the fetched artifact cache for export and related-artifact comparison.
- Related artifact metadata must not include artifact bodies.
- Continue/send/apply/revert/compare artifact actions prefill the composer rather than executing side effects in browser code.
- Recall cards render from streamed compact result items and reuse artifact body fetch, decision resolution, or composer prefill for actions.
- Loaded artifacts are cached in `state.artifacts` for the current browser session.
- Related artifact metadata is cached in `state.artifactRelated` for the current browser session.
- Decision cards resolve persisted Inbox items by id and keep status local to the card.
- Tool approval cards use the same decision resolution path and render any returned compact `tool_result` as an inline action/error card without adding browser persistence keys.
- Learning chips resolve or undo persisted memory candidates by id and keep status local to the card.
- Review-gated learning chips use `requires_confirmation` only for local presentation; they do not add browser persistence keys or a separate workflow.
- Settings drawer state is fetched on open through `/api/settings`; it is not persisted in browser storage.
- Settings drawer can update quiet hours through `/api/settings` and otherwise prefill the single composer for user-facing actions.
- `/api/settings` payloads must summarize learned preferences and data counts without raw artifact bodies, raw memory dumps, or provider secrets.
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
| User prompt replay | `turn.started` restores the visible user prompt and recent ask context | Asset behavior in `tests/test_web.py` |
| Activity de-duplication | Stable activity keys update existing rows instead of appending lifecycle duplicates | Asset behavior in `tests/test_web.py` |
| Artifact fetch | Returns stored artifact body plus compact related metadata by id and rejects missing/unknown ids | `tests/test_web.py` |
| Artifact viewer asset | Contains on-demand artifact fetch, body rendering, export, compare, and composer prefill hooks | `tests/test_web.py` |
| Recall card asset | Handles `recall.card`, compact item rendering, artifact open, decision resolve, and composer prefill hooks | `tests/test_web.py` |
| Inbox decision resolve | Resolves a persisted decision item and returns JSON errors for missing/invalid input | `tests/test_web.py` |
| Tool approval card | Uses the same decision resolution path, renders compact approval results, and adds no browser state keys | `tests/test_web.py`, `tests/test_runtime.py` |
| Learning memory action | Promotes, rejects, or undoes a persisted memory candidate and renders review-gated candidates as confirmation chips | `tests/test_web.py`, `tests/test_runtime.py` |
| Settings summary | Returns compact connected app, permission, quiet-hours, preference, and data-control data without secrets | `tests/test_web.py` |
| Settings update | Saves valid quiet-hours settings and rejects invalid time payloads with JSON errors | `tests/test_web.py` |
| Settings asset | Opens a drawer from chat and preloads settings through `/api/settings` | `tests/test_web.py` |
| Stop control | Requests run cancellation with active run id without clearing replay state | `tests/test_web.py` |
| Busy reset | Reset is disabled/guarded while a stream is active | `tests/test_web.py` |

### 5. Good/Base/Bad Cases
- Good: persist `event.event_id` after each processed chat event and use `sinceEventId` for incremental resume.
- Good: persist the recent user intent separately from ledger replay ids as `mnemo.last_user_intent`.
- Good: use an in-memory `activityRows` map for display de-duplication.
- Good: fetch artifact body via `/api/artifacts` after the user opens an artifact card.
- Good: export from an explicitly fetched body and keep related artifact lists compact.
- Good: express side-effectful artifact operations as composer intent so the normal model/tool/permission loop decides.
- Good: keep recall result bodies compact and fetch/open only the selected artifact body.
- Good: resolve decision cards by item id through `/api/inbox/resolve`, leaving conversation replay keys untouched.
- Good: resolve or undo learning chips by candidate id through `/api/learning/memory`, leaving conversation replay keys untouched.
- Good: keep `requires_confirmation` as streamed card-local presentation metadata.
- Good: fetch settings only when the drawer opens and keep ordinary user actions in composer prefill.
- Good: request cancellation and keep the stream open until the runtime emits completion.
- Good: clear `activeRunId` before each new turn so a stale replay id cannot be cancelled.
- Good: keep reset as an idle-only operation; use Stop for active run interruption.
- Base: sequence-based `since` remains available for CLI/debug callers.
- Bad: store ledger seq as frontend resume state.
- Bad: append replayed events without event-id de-duplication.
- Bad: persist activity rows or rendered cards in browser storage.
- Bad: put full artifact bodies in every `artifact.card` event.
- Bad: execute send/apply/revert directly in browser code.
- Bad: abort the active stream immediately after requesting cancellation and miss the final `run.completed`.
- Bad: send cancellation with `lastRunId` while a new stream is still waiting for its first event.
- Bad: clearing localStorage/timeline while a stream is still appending events.
- Bad: storing provider secrets or raw memory/artifact bodies in settings payloads.

### 6. Tests Required
- Web replay API supports full replay and `sinceEventId`.
- Unknown `sinceEventId` returns a safe full replay.
- Frontend asset includes resume persistence and de-duplication logic.
- Frontend asset restores user prompts from `turn.started` and updates the compact context panel.
- Frontend asset de-duplicates activity rows with stable keys.
- Artifact API covers success, missing id, and unknown id.
- Artifact API includes compact same-mission related artifact metadata without bodies.
- Frontend asset includes on-demand artifact body loading, browser export, comparison options, and composer-prefill artifact actions.
- Recall card rendering covers compact items and actions without additional browser persistence keys.
- Inbox API covers listing and resolution, including missing and invalid resolution errors.
- Frontend asset includes inline decision resolution hooks.
- Learning memory API covers accept, this-turn-only, reject, undo, missing candidate, and invalid action errors.
- Frontend asset includes inline learning resolution hooks and review-gated confirmation wording.
- Settings API covers summary, quiet-hours update, invalid time errors, and no secret leakage.
- Frontend asset includes settings drawer hooks and composer-prefill actions.
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
