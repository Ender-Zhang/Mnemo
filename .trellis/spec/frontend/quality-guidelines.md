# Quality Guidelines

## Scenario: Lightweight Web UI Quality Gate

### 1. Scope / Trigger
- Trigger: changes to web routes, static assets, chat rendering, event replay, or artifact viewing.
- Goal: keep the no-build frontend reliable, accessible, and package-safe.

### 2. Required Patterns
- Preserve one user-facing chat composer as the primary interaction.
- Keep stream events compact; fetch large bodies through explicit APIs.
- Use `textContent` for model/tool/user-controlled content.
- Render assistant Markdown with DOM-created nodes and `textContent`, not `innerHTML`.
- Keep live streaming readable as plain text before final Markdown formatting.
- Keep layout responsive with stable widths, wrapping, and no overlapping text.
- Keep stdout clean for CLI stream/JSON tests; web asset tests should not require a browser.

### 3. Forbidden Patterns
- No `innerHTML` for dynamic content.
- No frontend build step unless there is a concrete product need.
- No hidden dashboard-first flow for normal user tasks.
- No raw API keys, provider headers, or full provider request payloads in browser-visible data.
- No large artifact bodies in `artifact.card` stream payloads.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Static assets | Serve installed HTML/CSS/JS | `tests/package_install_smoke.py`, `tests/test_web.py` |
| Stream transport | NDJSON events remain parseable | `tests/test_web.py`, `tests/test_cli.py` |
| Replay | Event id de-duplication prevents duplicate cards | `tests/test_web.py` |
| Markdown rendering | Model output is formatted without unsafe HTML injection | `tests/test_web.py` |
| Activity trace | Action lifecycle events update existing right-panel rows | `tests/test_web.py` |
| Artifact body/actions | Body and related metadata fetched on demand; actions stay compact and composer-led | `tests/test_web.py` |
| Run cancellation | Stop control calls `/api/runs/cancel` with active run id and preserves stream/replay contracts | `tests/test_web.py` |
| Busy reset | New/reset is disabled while a stream is active | `tests/test_web.py` |
| Settings drawer | Fetches compact settings on open, saves quiet hours, and does not expose provider secrets | `tests/test_web.py` |
| Long text | Uses wrapping styles and stable dimensions | CSS/asset review |

### 5. Good/Base/Bad Cases
- Good: add a test that reads `app.js` and checks for a new event route when adding a new card type.
- Good: add asset tests for Markdown helpers and assert `innerHTML` is absent.
- Good: assert activity de-duplication helpers when changing event rendering.
- Good: update package data tests when adding a new static asset.
- Base: manual browser smoke is useful for layout changes but unit tests should cover contracts.
- Bad: relying only on manual visual inspection for replay or stream behavior.

### 6. Tests Required
- Run `python -m unittest tests.test_web tests.test_cli` for web/CLI transport changes.
- Run full source tests before committing cross-layer UI/runtime changes.
- Run package smoke when adding, moving, or renaming web assets.
