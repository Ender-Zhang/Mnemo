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
- Runtime state: `state.pendingAssistantNode: HTMLElement | null`
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
- API: `POST /api/settings` with JSON `{ "quiet_hours"?: { "enabled": boolean, "start": "HH:MM", "end": "HH:MM", "timezone"?: string }, "runtime"?: { "provider"?: string, "model"?: string, "base_url"?: string, "api_key_env"?: string, "timeout_s"?: number, "retry_count"?: number, "retry_backoff_s"?: number } }`
- API: `GET /api/memory/ontology` returns L1 compact ten-dimensional memory counts, short summaries, and per-dimension drill-down URLs.
- API: `GET /api/memory/ontology` returns exactly the configured ten user-facing dimensions; historical labels such as profile, finance, or work-style must already be normalized by the API.
- API: `GET /api/memory/dimension?dimension=<dimension>` returns L2 clipped page/candidate cards for one normalized dimension.
- API: `GET /api/memory/item?type=page|candidate&id=<id>` returns L3 clipped item detail plus compact evidence rows and markdown detail text.
- API: `GET /api/memory/item?type=page|candidate&id=<id>` markdown is a wiki note, not a metadata dump: frontmatter, one title, concise body, optional evidence section.

### 3. Contracts
- The browser stores durable conversation, mission, last run, and last processed chat event ids in `localStorage`.
- `last_event_id` is always a `ChatEvent.event_id`, not a SQLite `run_events.seq`.
- On page load, the web client replays the last run if `mnemo.last_run_id` exists.
- When the visible timeline is empty, replay fetches all chat events for the last run.
- Incremental resume uses `sinceEventId` and appends only later events.
- The client must de-duplicate events by `event_id` before mutating the timeline.
- `turn.started` replay should restore the user prompt into the timeline when the client is not busy.
- `mnemo.last_user_intent` stores only a compact recent prompt summary for the browser-local context panel.
- Tool activity rows are volatile browser state and must be rebuilt from stream/replay events, not stored in `localStorage`.
- Background learning action events marked with `internal="learning"` are ignored by the visible activity timeline.
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
- Ordinary learning candidates do not create visible confirmation chips.
- Learning chips resolve or undo persisted review-gated memory candidates by id and keep status local to the card.
- Review-gated learning chips use `requires_confirmation` only for local presentation; they do not add browser persistence keys or a separate workflow.
- `/api/settings` can seed read-only chat glance cards on page load and hydrate the settings view on open; it is not persisted in browser storage except lightweight local UI toggles.
- Settings view can update quiet hours and runtime provider preferences through `/api/settings`; raw API keys must never be sent or stored, only an environment variable name.
- Runtime settings are live overlays: unset fields must continue using process startup config, while saved provider/model/base URL, API key env, timeout, and retry fields override future web turns.
- `/api/settings` payloads must summarize learned preferences, runtime preferences, and data counts without raw artifact bodies, raw memory dumps, or provider secrets.
- `/api/memory/ontology` is a read-only memory compass view; it must summarize ten-dimensional L1 memory coverage without provider secrets, item arrays, or unbounded raw memory bodies.
- The memory compass must fetch L2 dimension cards only after the user selects a dimension.
- The memory compass must fetch L3 evidence and markdown only after the user selects a memory page or candidate.
- Memory markdown detail panels must render the API-provided wiki note in the memory page itself; labels, frontmatter, and de-duplicated candidate wording are backend contracts.
- L2 and L3 memory responses are cached only in volatile runtime maps for the current browser session; they must not add browser persistence keys.
- Enter submits the composer while Shift+Enter inserts a newline.
- After a user submits a turn, the client renders one volatile pending assistant message until the first assistant delta, final message, run error, or stream error arrives.
- A failed stream should produce one visible error card; if the runtime has already emitted `run.error`, the web transport must not add a second `server.error`.
- Pending assistant state must never be persisted in browser storage.
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
| Normal learning candidate | Ordinary memory/skill/tool/eval candidate writes remain background events without visible confirmation chips | `tests/test_runtime.py` |
| Learning memory action | Promotes, rejects, or undoes a persisted memory candidate and renders review-gated candidates as review chips | `tests/test_web.py`, `tests/test_runtime.py` |
| Settings summary | Returns compact connected app, permission, quiet-hours, runtime, preference, and data-control data without secrets | `tests/test_web.py` |
| Settings update | Saves valid quiet-hours/runtime settings and rejects invalid time or secret-bearing payloads with JSON errors | `tests/test_web.py` |
| Settings asset | Opens a settings view and preloads settings through `/api/settings` | `tests/test_web.py` |
| Memory ontology asset | Opens compact ten-dimensional L1 coverage from the memory compass view | `tests/test_web.py` |
| Memory ontology API | Returns compact L1 dimension counts/summaries without secrets or item arrays | `tests/test_web.py` |
| Memory dimension asset/API | Loads one L2 dimension on demand with clipped cards | `tests/test_web.py` |
| Memory item asset/API | Loads one L3 item on demand with compact evidence and markdown detail text | `tests/test_web.py` |
| Enter submit | Enter sends and Shift+Enter remains newline-capable | Asset behavior in `tests/test_web.py` |
| Pending assistant | Volatile reply indicator appears during stream wait and is cleaned up | Asset behavior in `tests/test_web.py` |
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
- Good: fetch settings only when the settings view opens and keep ordinary user actions in the chat composer.
- Good: keep ten-dimensional memory inspection read-only and memory-view-scoped.
- Good: reveal memory progressively instead of dumping every page, candidate, evidence row, and markdown body into the first L1 payload.
- Good: keep pending assistant UI as volatile DOM state.
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
- Bad: rendering the same tool result as an action card and as a separate source card in the main timeline.
- Bad: persisting pending assistant indicators or other transient stream UI in localStorage.

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
- Frontend asset includes inline learning resolution hooks and review-gated review wording.
- Frontend asset includes Enter-to-send handling and volatile pending assistant cleanup.
- Frontend asset includes `/api/memory/ontology`, `/api/memory/dimension`, and `/api/memory/item` memory compass loading.
- Memory ontology API covers ten dimensions, L1-only payload shape, and compact body/secret behavior.
- Memory dimension and item APIs cover L2/L3 on-demand disclosure.
- Settings API covers summary, quiet-hours update, runtime provider update, invalid time/secret errors, and no secret leakage.
- Frontend asset includes settings view hooks and runtime provider controls.
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
