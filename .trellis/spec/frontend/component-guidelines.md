# Component Guidelines

## Scenario: DOM Components Without A Framework

### 1. Scope / Trigger
- Trigger: changes to timeline rendering, composer controls, action cards, artifact cards, decision cards, recall cards, learning chips, memory compass, or settings page controls.
- Goal: keep the UI understandable as a single product shell where chat remains the execution surface and memory/settings remain lightweight inspection/configuration surfaces.

### 2. Component Patterns
- Components are DOM builder/render functions in `mnemo/interfaces/web_assets/app.js`.
- Reusable visual units are CSS classes in `app.css`: `.message`, `.event-card`, `.event-title`, `.event-body`, `.composer`.
- The primary screen is always the chat view: top status, timeline, and one composer.
- Navigation state may live in the URL hash so refresh/back/deep links keep the selected view without adding a second task surface.
- On mobile, the primary navigation should move to a compact bottom bar while the header stays focused on the Mnemo brand and lightweight commands.
- Mobile bottom navigation must keep the primary chat, memory, and settings entries visible as equal-width items.
- Tool and learning activity appears inline as compact cards, not separate dashboards.
- Chat empty state may show read-only glance cards for current runtime, memory counts, and latest activity; these cards must not become a second task surface.
- Desktop chat may show a read-only context rail for real-time activity, recent request, runtime, and memory summary; it must hide on smaller screens and must not expose Mission/Run internals beyond compact resume labels.
- Busy-state commands such as stop/cancel belong inside the existing composer.
- The composer input remains editable while a run is busy so the user can draft the next turn; sending is disabled until the current run finishes.
- Programmatic composer writes from suggestions, recall rows, artifacts, memory actions, and toolbar buttons must refresh composer state immediately.
- New conversation reset must clear the composer draft and visible activity rows so the user sees a clean chat surface.
- Low-frequency settings live in a settings view launched from navigation; they must not become a dashboard-first flow for normal tasks.

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
- Normal learning candidates should stay unobtrusive: background learning writes are not visible confirmation chips in the main timeline.
- Learning chips are reserved for exceptional review-gated memory candidates and resolve or undo memory candidates through `/api/learning/memory`.
- Learning chips with `requires_confirmation=true` should use review wording, not routine confirmation wording, before durable memory promotion.
- The settings view renders compact connected-app, permission, quiet-hours, runtime provider/model, preference, and data-control summaries from `/api/settings`.
- Settings provider tiles may prefill the Provider form, but they must not save runtime changes until the normal settings submit path runs.
- Runtime provider settings include bounded operational controls such as timeout, retry count/backoff, and `max_tool_rounds`; these controls must stay in the settings view and must not create a separate task execution surface.
- Settings provider tiles and the Provider select must stay visually synchronized before save.
- Ten-dimensional memory inspection lives in the memory compass view through progressive disclosure: `/api/memory/ontology` shows L1 coverage, `/api/memory/dimension` shows L2 clipped cards, and `/api/memory/item` shows L3 compact evidence plus markdown for a selected item.
- The memory compass can mirror L1 dimensions as an orbit around the avatar, but orbit buttons must call the same L2 dimension loader and remain read-only.
- Settings actions should save narrow settings only; ordinary user tasks still route through the single composer.
- Assistant Markdown must be rendered by DOM builder helpers, never by assigning model output to `innerHTML`.
- Streaming assistant deltas should render as safe Markdown DOM from `dataset.rawText`; final `assistant.message` or `run.completed` re-renders the same source.
- Memory Wiki Markdown frontmatter delimited by `---` must remain visible as a raw `markdown-frontmatter` metadata block before the rendered body; do not drop it or collapse it into an ordinary paragraph.
- Memory Wiki panels must extract the Markdown H1 into the panel header so the title remains visible even when frontmatter is rendered first.
- Markdown headings must receive deterministic ids for same-note links. Memory Wiki cross-entry links should use backend/model-provided title-based wiki file paths such as `wiki/preferences/communication-style.md`; hash-only links stay same-page and must not be forced into a new browser tab.
- Replayed `turn.started` events should render the historical user prompt when the client is not actively streaming a new turn.
- Tool activity rows should upsert by stable event/action keys so queued, started, and completed action events update one compact card.
- Internal learning housekeeping, including after-turn learning action lifecycle events, `learning_discard`, and learning-tone status updates, should not appear as visible Activity rows.
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
| Normal learning candidate | Does not render a visible confirmation chip for ordinary background learning | `tests/test_runtime.py` |
| Learning chip | Shows compact review text, accept/this-turn/reject, and post-resolution undo actions for exceptional review-gated memory | `tests/test_web.py`, `tests/test_runtime.py` |
| Settings page | Shows compact low-frequency settings, saves quiet hours and runtime provider preferences, including `max_tool_rounds`, without raw secrets | `tests/test_web.py` |
| Memory compass page | Loads compact L1 coverage, then L2/L3 memory detail and markdown on demand without raw secrets | `tests/test_web.py` |
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
- Good: keep the composer textarea editable during a running answer while disabling only send.
- Good: call `updateComposerState()` after `prefillMessage()` or `insertComposerText()` changes the textarea.
- Good: reset visible rail activity and composer draft when starting a new conversation.
- Good: use equal-width mobile bottom navigation so chat, memory, and settings remain one tap away.
- Good: resolve a Decision card with small inline buttons rather than opening a separate Inbox dashboard.
- Good: render approved tool execution as a compact action/error card returned from the resolve API.
- Good: expose tool arguments/results in collapsible details on the same action card.
- Good: render Recall results as inline item rows with buttons that open artifacts, resolve decisions, or prefill the composer.
- Good: resolve or undo a Learning chip with small inline buttons rather than opening a memory dashboard.
- Good: label review-gated Learning chip acceptance as an explicit confirmation instead of casual preference learning.
- Good: keep data-control actions compact and route task-like follow-ups back to the single composer.
- Good: inspect ten-dimensional memory from the memory compass as a compact, read-only view.
- Good: keep evidence chains behind explicit item selection.
- Good: use `document.createElement`, `textContent`, and `replaceChildren` for Markdown blocks and inline marks.
- Good: store streaming Markdown source in `dataset.rawText` before final formatting.
- Good: filter internal learning maintenance by `internal="learning"` or status tone metadata before rendering Activity rows.
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
- For learning actions, assert the asset calls `/api/learning/memory`, disables buttons while resolving, exposes post-resolution undo, and uses review wording for review-gated items.
- For settings, assert the asset calls `/api/settings`, renders the settings view, saves provider/runtime and quiet-hours settings, and never exposes raw provider secrets.
- For memory ontology, assert `/api/memory/ontology`, `/api/memory/dimension`, `/api/memory/item`, and memory compass assets expose progressive L1/L2/L3 disclosure with in-page markdown detail viewing.
- For Markdown, assert DOM builder helpers exist, `innerHTML` is absent, and Markdown CSS classes are present.
- For Memory Wiki Markdown, assert frontmatter helpers and `.markdown-frontmatter` styling are present so the raw metadata block remains visible.
- For activity rows, assert `activityRows`, `activityActionId`, and compact tool-card upsert behavior are present.
- For internal learning housekeeping, assert `isInternalLearningEvent`, `internal === "learning"`, `tone === "learning"`, and `learning_discard` filters are present.
