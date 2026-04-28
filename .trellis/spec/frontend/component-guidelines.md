# Component Guidelines

## Scenario: DOM Components Without A Framework

### 1. Scope / Trigger
- Trigger: changes to timeline rendering, composer controls, action cards, artifact cards, decision cards, recall cards, learning chips, or settings drawer controls.
- Goal: keep the UI understandable as a single chat surface while supporting rich action visibility.

### 2. Component Patterns
- Components are DOM builder/render functions in `mnemo/interfaces/web_assets/app.js`.
- Reusable visual units are CSS classes in `app.css`: `.message`, `.event-card`, `.event-title`, `.event-body`, `.composer`.
- The primary screen is always the chat shell: top status, timeline, and one composer.
- Tool and learning activity appears inline as compact cards, not separate dashboards.
- Busy-state commands such as stop/cancel belong inside the existing composer.
- Low-frequency settings live in a drawer launched from the chat top bar; they must not become a dashboard-first flow.

### 3. Contracts
- Render functions must tolerate missing optional fields with concise fallbacks.
- Dynamic text must use `textContent`, not `innerHTML`.
- Cards should render compact metadata first and fetch large bodies only after user action.
- Artifact cards should provide compact actions for continuing, exporting, comparing, sending, and diff apply/revert intent without leaving the chat surface.
- Decision cards should stay inline in the timeline and resolve through `/api/inbox/resolve`.
- Tool approval cards reuse the same inline Decision Card renderer and should show only compact tool metadata plus compact execution results returned by the resolve API.
- Tool action cards should show one compact call/result surface; duplicate `tool_result` source cards are suppressed in the main timeline.
- Recall cards should stay inline in the timeline, show compact result items, and use existing artifact/decision/composer actions.
- Recall item titles and summaries should not repeat the same text.
- Learning chips should stay inline in the timeline and resolve or undo memory candidates through `/api/learning/memory`.
- Learning chips with `requires_confirmation=true` should use explicit confirmation wording before durable memory promotion.
- The settings drawer renders compact connected-app, permission, quiet-hours, preference, and data-control summaries from `/api/settings`.
- Ten-dimensional memory inspection lives in the settings drawer through `/api/memory/ontology` and shows compact coverage, counts, and clipped item summaries.
- Settings drawer actions should either save narrow settings or prefill the single composer for normal user intent.
- Assistant Markdown must be rendered by DOM builder helpers, never by assigning model output to `innerHTML`.
- Streaming assistant deltas should render as safe Markdown DOM from `dataset.rawText`; final `assistant.message` or `run.completed` re-renders the same source.
- Replayed `turn.started` events should render the historical user prompt when the client is not actively streaming a new turn.
- Right-side activity rows should upsert by stable event/action keys so queued, started, and completed action events update one row.
- Internal learning housekeeping, including `learning_discard` action lifecycle events and learning-tone status updates, should not appear as visible Activity rows.
- Buttons must have clear text or `title` attributes when their action is not obvious.
- Text containers must use wrapping constraints so long ids, URLs, and tool names do not overflow.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Assistant delta | Appends into one assistant message node | Asset behavior in `tests/test_web.py` |
| Action event | Renders queued/started/completed card state | Asset behavior in `tests/test_web.py` |
| Tool details | Action cards expose compact call arguments and completed result without duplicate source cards | `tests/test_web.py`, `tests/test_runtime.py` |
| Artifact card | Shows metadata, opens body on demand, exports, compares related artifacts, and pre-fills composer actions | `tests/test_web.py` |
| Decision card | Shows compact decision text and approve/reject/ignore actions | `tests/test_web.py` |
| Tool approval card | Denied external/admin tool calls project through the existing decision card path and accepted approvals show compact tool results | `tests/test_web.py`, `tests/test_runtime.py` |
| Recall card | Shows compact past-work/artifact/decision/knowledge result items with actions | `tests/test_web.py` |
| Learning chip | Shows compact learning text, high-risk confirmation wording, accept/this-turn/reject, and post-resolution undo actions | `tests/test_web.py`, `tests/test_runtime.py` |
| Settings drawer | Shows compact low-frequency settings, saves quiet hours, and reuses composer prefill actions | `tests/test_web.py` |
| Memory ontology drawer | Loads compact ten-dimensional memory coverage without raw secrets | `tests/test_web.py` |
| Markdown assistant message | Renders headings, lists, code, emphasis, and links with DOM-created nodes | Asset behavior in `tests/test_web.py` |
| Activity upsert | Merges action lifecycle events into a stable row | Asset behavior in `tests/test_web.py` |
| Internal learning housekeeping | Suppresses `learning_discard` and learning-tone status from visible activity | Asset behavior in `tests/test_web.py` |
| Duplicate replay event | Ignored by `renderedEventIds` | `tests/test_web.py` |
| Stop control | Appears as a composer command while a run is busy | `tests/test_web.py` |
| Error event | Renders visible error card | Manual/asset check |

### 5. Good/Base/Bad Cases
- Good: `card.querySelector(".event-body").textContent = summary`.
- Good: keep all user task interaction in the single composer.
- Good: use artifact card buttons to prefill composer intent for model/tool-led follow-up work.
- Good: use a busy-state composer button for run cancellation instead of a separate operations area.
- Good: resolve a Decision card with small inline buttons rather than opening a separate Inbox dashboard.
- Good: render approved tool execution as a compact action/error card returned from the resolve API.
- Good: expose tool arguments/results in collapsible details on the same action card.
- Good: render Recall results as inline item rows with buttons that open artifacts, resolve decisions, or prefill the composer.
- Good: resolve or undo a Learning chip with small inline buttons rather than opening a memory dashboard.
- Good: label review-gated Learning chip acceptance as an explicit confirmation instead of casual preference learning.
- Good: let data-control actions prefill the single composer instead of adding a separate data-management screen.
- Good: inspect ten-dimensional memory from settings as a compact, read-only view.
- Good: use `document.createElement`, `textContent`, and `replaceChildren` for Markdown blocks and inline marks.
- Good: store streaming Markdown source in `dataset.rawText` before final formatting.
- Good: filter internal learning maintenance by event metadata such as tool name and status tone.
- Base: small helper functions can create DOM nodes directly.
- Bad: `element.innerHTML = modelOutput`.
- Bad: adding a second operations dashboard for normal user workflows.

### 6. Tests Required
- For new card types, add asset assertions and API/projection tests where possible.
- For tool action rendering, assert call/result details render once and `tool_result` source cards are suppressed.
- For artifact/body changes, assert streamed events remain compact and related artifact lists omit bodies.
- For artifact actions, assert the asset supports export, compare, continue/send, and patch apply/revert composer prefill.
- For decision actions, assert the asset calls `/api/inbox/resolve` and disables buttons while resolving.
- For recall cards, assert the asset handles `recall.card` and does not require a separate dashboard route.
- For recall cards, assert repeated title/summary text is compacted.
- For learning actions, assert the asset calls `/api/learning/memory`, disables buttons while resolving, exposes post-resolution undo, and uses confirmation wording for review-gated items.
- For settings, assert the asset calls `/api/settings`, renders the drawer, and reuses composer prefill for user actions.
- For memory ontology, assert `/api/memory/ontology` and settings drawer assets expose compact ten-dimensional coverage.
- For Markdown, assert DOM builder helpers exist, `innerHTML` is absent, and Markdown CSS classes are present.
- For activity rows, assert `activityRows`, `activityActionId`, and `upsertActivity` are present.
- For internal learning housekeeping, assert `isInternalLearningEvent`, `tone === "learning"`, and `learning_discard` filters are present.
