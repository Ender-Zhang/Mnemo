# Component Guidelines

## Scenario: DOM Components Without A Framework

### 1. Scope / Trigger
- Trigger: changes to timeline rendering, composer controls, action cards, artifact cards, decision cards, or learning chips.
- Goal: keep the UI understandable as a single chat surface while supporting rich action visibility.

### 2. Component Patterns
- Components are DOM builder/render functions in `mnemo/interfaces/web_assets/app.js`.
- Reusable visual units are CSS classes in `app.css`: `.message`, `.event-card`, `.event-title`, `.event-body`, `.composer`.
- The primary screen is always the chat shell: top status, timeline, and one composer.
- Tool and learning activity appears inline as compact cards, not separate dashboards.
- Busy-state commands such as stop/cancel belong inside the existing composer.

### 3. Contracts
- Render functions must tolerate missing optional fields with concise fallbacks.
- Dynamic text must use `textContent`, not `innerHTML`.
- Cards should render compact metadata first and fetch large bodies only after user action.
- Decision cards should stay inline in the timeline and resolve through `/api/inbox/resolve`.
- Learning chips should stay inline in the timeline and resolve memory candidates through `/api/learning/memory`.
- Buttons must have clear text or `title` attributes when their action is not obvious.
- Text containers must use wrapping constraints so long ids, URLs, and tool names do not overflow.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Assistant delta | Appends into one assistant message node | Asset behavior in `tests/test_web.py` |
| Action event | Renders queued/started/completed card state | Asset behavior in `tests/test_web.py` |
| Artifact card | Shows metadata and opens body on demand | `tests/test_web.py` |
| Decision card | Shows compact decision text and approve/reject/ignore actions | `tests/test_web.py` |
| Learning chip | Shows compact learning text and accept/this-turn/reject actions | `tests/test_web.py` |
| Duplicate replay event | Ignored by `renderedEventIds` | `tests/test_web.py` |
| Stop control | Appears as a composer command while a run is busy | `tests/test_web.py` |
| Error event | Renders visible error card | Manual/asset check |

### 5. Good/Base/Bad Cases
- Good: `card.querySelector(".event-body").textContent = summary`.
- Good: keep all user task interaction in the single composer.
- Good: use a busy-state composer button for run cancellation instead of a separate operations area.
- Good: resolve a Decision card with small inline buttons rather than opening a separate Inbox dashboard.
- Good: resolve a Learning chip with small inline buttons rather than opening a memory dashboard.
- Base: small helper functions can create DOM nodes directly.
- Bad: `element.innerHTML = modelOutput`.
- Bad: adding a second operations dashboard for normal user workflows.

### 6. Tests Required
- For new card types, add asset assertions and API/projection tests where possible.
- For artifact/body changes, assert streamed events remain compact.
- For decision actions, assert the asset calls `/api/inbox/resolve` and disables buttons while resolving.
- For learning actions, assert the asset calls `/api/learning/memory` and disables buttons while resolving.
