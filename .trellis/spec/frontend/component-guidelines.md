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

### 3. Contracts
- Render functions must tolerate missing optional fields with concise fallbacks.
- Dynamic text must use `textContent`, not `innerHTML`.
- Cards should render compact metadata first and fetch large bodies only after user action.
- Buttons must have clear text or `title` attributes when their action is not obvious.
- Text containers must use wrapping constraints so long ids, URLs, and tool names do not overflow.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Assistant delta | Appends into one assistant message node | Asset behavior in `tests/test_web.py` |
| Action event | Renders queued/started/completed card state | Asset behavior in `tests/test_web.py` |
| Artifact card | Shows metadata and opens body on demand | `tests/test_web.py` |
| Duplicate replay event | Ignored by `renderedEventIds` | `tests/test_web.py` |
| Error event | Renders visible error card | Manual/asset check |

### 5. Good/Base/Bad Cases
- Good: `card.querySelector(".event-body").textContent = summary`.
- Good: keep all user task interaction in the single composer.
- Base: small helper functions can create DOM nodes directly.
- Bad: `element.innerHTML = modelOutput`.
- Bad: adding a second operations dashboard for normal user workflows.

### 6. Tests Required
- For new card types, add asset assertions and API/projection tests where possible.
- For artifact/body changes, assert streamed events remain compact.
