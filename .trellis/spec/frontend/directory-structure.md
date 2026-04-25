# Directory Structure

## Scenario: Stdlib Single-Chat Frontend

### 1. Scope / Trigger
- Trigger: changes to `mnemo/interfaces/web.py` or `mnemo/interfaces/web_assets/*`.
- Goal: keep the frontend lightweight, user-facing, and aligned with the single-chat product model.

### 2. Directory Layout
```text
mnemo/interfaces/
  web.py              stdlib HTTP server and JSON/NDJSON API handlers
  web_assets/
    index.html        single chat shell
    app.css           responsive visual styling
    app.js            stream reader, event rendering, replay/resume
tests/test_web.py     API and static asset behavior tests
```

### 3. Contracts
- There is no frontend build step and no `src/` frontend tree.
- Static assets must remain package data so installed wheels can serve the web UI.
- `web.py` owns HTTP routing and provider selection; browser logic stays in `app.js`.
- `app.js` owns client state, NDJSON parsing, event de-duplication, and card rendering.
- `app.css` owns layout and visual styling; avoid inline styles in generated DOM.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Installed package | Web assets are present in the wheel | `tests/package_install_smoke.py` |
| Static asset serving | HTML/CSS/JS served by stdlib server | `tests/test_web.py` |
| Chat stream | `/api/chat` returns NDJSON ChatEvent records | `tests/test_web.py` |
| Replay | `/api/events` supports full and incremental replay | `tests/test_web.py` |
| Artifact viewer | `/api/artifacts` fetches body and compact related metadata on demand | `tests/test_web.py` |
| Settings drawer | `/api/settings` serves compact settings summaries and web assets render the drawer | `tests/test_web.py` |

### 5. Good/Base/Bad Cases
- Good: add new UI behavior by extending `app.js` render functions and asserting asset text in `tests/test_web.py`.
- Good: keep API payloads compact and fetch large bodies explicitly.
- Base: CSS uses stable classes and responsive constraints.
- Bad: adding a frontend bundler for a small asset-only change.
- Bad: embedding raw artifact bodies in stream events.

### 6. Tests Required
- Update `tests/test_web.py` for route or asset behavior.
- Run package smoke when asset packaging changes.
