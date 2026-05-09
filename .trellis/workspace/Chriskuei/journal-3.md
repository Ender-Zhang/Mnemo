# Journal - Chriskuei (Part 3)

> Continuation from `journal-2.md` (archived at ~2000 lines)
> Started: 2026-04-27

---



## Session 115: Core API Watch Cron schedule surface

**Date**: 2026-04-27
**Task**: Core API Watch Cron schedule surface
**Branch**: `main`

### Summary

Added compact SDK and HTTP Core API registration surfaces for Watch and Cron scheduled items, wired schema/OpenAPI/CLI schema/package smoke coverage, and synced design/spec/checklist while preserving scheduler/daemon execution ownership.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `af76b2d` | (see git log) |
| `d0d4d0a` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 116: Redesign single-chat frontend

**Date**: 2026-04-27
**Task**: Redesign single-chat frontend
**Branch**: `main`

### Summary

Generated a new single-chat product direction and implemented it in the stdlib Web UI: rail shell, refined chat canvas, contextual activity panel, universal composer affordances, preserved inline action/decision/learning/artifact/recall/settings behavior, and added asset coverage with full tests and package smoke passing.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8128428` | (see git log) |
| `f59fa89` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 117: Polish reference frontend and Markdown

**Date**: 2026-04-27
**Task**: Polish reference frontend and Markdown
**Branch**: `main`

### Summary

Polished the single-chat frontend toward the generated reference with labeled rail navigation, compact user context, safe DOM-built Markdown rendering, replayed user prompts, de-duplicated activity rows, refreshed frontend specs, asset tests, full tests, and package smoke.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e81ed70` | (see git log) |
| `8efa3ba` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 118: Gate low-signal learning reflection

**Date**: 2026-04-27
**Task**: Gate low-signal learning reflection
**Branch**: `main`

### Summary

Added a structure-only evidence gate before after-turn provider learning reflection, skipping zero/low-tool turns without a second model call, hiding internal learning housekeeping in Web Activity, updating frontend/backend specs, and covering the runtime and web asset behavior with tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `664e6a7` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 119: Polish chat interactions and memory view

**Date**: 2026-04-28
**Task**: Polish chat interactions and memory view
**Branch**: `main`

### Summary

(Add summary)

### Main Changes

| Area | Summary |
|------|---------|
| Frontend | Added Enter-to-send, Shift+Enter newline preservation, volatile reply pending animation, compact tool call/result details, duplicate tool-result source suppression, and recall title/summary compaction. |
| Memory UI/API | Added `/api/memory/ontology` and settings-drawer ten-dimensional memory inspection with compact counts and clipped summaries. |
| Runtime Events | Added compact `result` payloads to `action.completed` events for local/provider runtimes with argument/result redaction and clipping. |
| Specs/Checklist | Updated frontend state/component contracts, memory engine contract, and implementation checklist. |
| Validation | Ran `node --check mnemo/interfaces/web_assets/app.js`, `git diff --check`, `python -m unittest tests.test_web tests.test_runtime`, full `python -m unittest discover -s tests` (328 tests), and wheel install smoke. |


### Git Commits

| Hash | Message |
|------|---------|
| `241dafb` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 120: Feishu channel and one-click install

**Date**: 2026-05-08
**Task**: Feishu channel and one-click install
**Branch**: `main`

### Summary

Added dependency-light Feishu/Lark webhook channel, one-click installer, docs/notices/spec contracts, and tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `6a14438` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 121: Feishu QR onboarding

**Date**: 2026-05-08
**Task**: Feishu QR onboarding
**Branch**: `main`

### Summary

Added Feishu/Lark scan-to-create QR onboarding, saved channel config/status, optional websocket serving, Web settings controls, docs/specs, and tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `674a890` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 122: Install Onboard Service

**Date**: 2026-05-08
**Task**: Install Onboard Service
**Branch**: `main`

### Summary

Added unified install onboarding, service management, API credential setup, and Feishu binding flow.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4a26857` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 123: Feishu Service Sidecar

**Date**: 2026-05-09
**Task**: Feishu Service Sidecar
**Branch**: `main`

### Summary

Diagnosed bound Feishu bots not replying because only the web process was running, added an automatic websocket Feishu sidecar to the Mnemo service launcher, verified mem.day.qzz.io and live listener health, and covered sidecar inclusion/secret-redaction with CLI tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e099f45` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 124: Feishu Markdown And Web Auth

**Date**: 2026-05-09
**Task**: Feishu Markdown And Web Auth
**Branch**: `main`

### Summary

Rendered Feishu replies as rich post Markdown, added password-gated Web access through MNEMO_WEB_PASSWORD/MNEMO_WEB_PASSWORD_SHA256 with signed HttpOnly sessions, restarted mem.day.qzz.io with a local password, and verified tests plus deployment health.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e1f2360` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 125: Settings Standalone Page

**Date**: 2026-05-09
**Task**: Settings Standalone Page
**Branch**: `main`

### Summary

Converted Settings from drawer/mobile sheet behavior into a normal standalone hash-routed page, removed overlay markup and CSS, updated asset tests/specs, restarted mem.day.qzz.io, and verified tests plus package smoke.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f9f4361` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 126: Feishu streaming replies

**Date**: 2026-05-09
**Task**: Feishu streaming replies
**Branch**: `main`

### Summary

(Add summary)

### Main Changes

| Area | Summary |
|------|---------|
| Feishu channel | Added best-effort emoji reactions on inbound messages and streamed replies by sending a placeholder rich post, then editing the same message with throttled partial content. |
| Runtime integration | Routed Feishu websocket/webhook processing through `stream_local()` / `stream_provider()` while preserving the existing non-streaming helper for compatibility. |
| Resilience | Final edit failures now fall back to sending a new final rich-post reply, and reaction/edit failures do not block Mnemo processing. |
| Documentation | Updated backend integration contracts, README, and Hermes acknowledgement notices for reaction and streamed-edit behavior. |
| Verification | Passed `python -m unittest discover -s tests`, Feishu channel tests, CLI/Web/runtime/provider focused tests, package install smoke, and local/public `/api/health`; restarted `mnemo-web` and `mnemo-feishu`. |


### Git Commits

| Hash | Message |
|------|---------|
| `dbb69a5` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 127: Auto Dream Web Scheduler

**Date**: 2026-05-09
**Task**: Auto Dream Web Scheduler
**Branch**: `main`

### Summary

Added service-owned automatic Dream scheduling to `mnemo web`, kept execution provider-led with no deterministic promotion fallback, restarted the public service, and verified the first background Dream report.

### Main Changes

| Area | Summary |
|------|---------|
| Scheduler | Added `ensure_default_dream_schedule()` and `ScheduleService.tick(kind="dream")` so background ticks can create one default Dream trigger and avoid touching unrelated watch/cron work. |
| Web service | Started a daemon auto Dream scheduler from `serve_web()`; it reads live runtime settings, only runs provider-backed Dream, and leaves due items pending when only local runtime is available. |
| Documentation | Updated backend specs and README to document auto Dream as a trigger/budget surface, not a rules fallback. |
| Verification | Passed focused scheduler/web tests, the Dream/runtime/SDK/MCP/CLI/Web regression suite, `git diff --check`, public `/api/health`, Feishu websocket capture, and confirmed `.mnemo/runs/dream-reports/latest.json` from the first background run. |

### Git Commits

| Hash | Message |
|------|---------|
| `548b954` | feat(memory): auto-run dream from web service |

### Testing

- [OK] `.venv/bin/python -m unittest tests.test_scheduler tests.test_web`
- [OK] `.venv/bin/python -m unittest tests.test_memory tests.test_runtime tests.test_scheduler tests.test_mcp tests.test_sdk tests.test_cli tests.test_web`
- [OK] `git diff --check`
- [OK] `curl https://mem.day.qzz.io/api/health`
- [OK] First auto Dream schedule tick completed with `mode=model_tool_calls`.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 128: Feishu Official Streaming Cards

**Date**: 2026-05-09
**Task**: Feishu Official Streaming Cards
**Branch**: `main`

### Summary

Replaced the default Feishu reply streaming path with official CardKit streaming cards, kept rich-post edit streaming as an explicit fallback, restarted the public web/Feishu services, and verified the tunnel.

### Main Changes

| Area | Summary |
|------|---------|
| Feishu channel | Added `FeishuStreamingCard` plus CardKit create/update/close helpers using interactive card replies and `streaming=true` by default. |
| Configuration | Added `--streaming` / `--no-streaming`, `FEISHU_STREAMING`, saved-config/status `streaming`, and service sidecar propagation. |
| Fallback | Kept the old rich-post edit loop only for disabled streaming or startup fallback; final card close failures send a normal Markdown reply. |
| Documentation | Updated README and backend contracts to acknowledge Feishu official/OpenClaw streaming-card behavior and document the API boundary. |

### Git Commits

| Hash | Message |
|------|---------|
| `d3b554e` | feat(channels): use Feishu streaming cards |

### Testing

- [OK] `.venv/bin/python -m unittest tests.test_channels tests.test_cli`
- [OK] `.venv/bin/python -m unittest tests.test_channels tests.test_cli tests.test_web`
- [OK] `git diff --check`
- [OK] Restarted `mnemo-web` and `mnemo-feishu`; local and public `/api/health` passed, and Feishu websocket connected with `--streaming`.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 129: Hide Feishu Stream Placeholder

**Date**: 2026-05-09
**Task**: Hide Feishu Stream Placeholder
**Branch**: `main`

### Summary

(Add summary)

### Main Changes

### Summary

Removed the visible Feishu reply startup text so official streaming cards and legacy rich-post fallback start with an invisible placeholder until the first model content arrives.

### Main Changes

| Area | Summary |
|------|---------|
| Feishu channel | Changed the initial streaming placeholder from visible `正在思考...` text to a zero-width placeholder while preserving card create/update/close behavior. |
| Fallback | Updated the legacy rich-post fallback expectation so the first temporary post is invisible before throttled stream edits replace it. |
| Specification | Updated the backend Feishu integration contract to document the invisible placeholder behavior. |
| Verification | Passed channel/CLI tests, checked whitespace, restarted `mnemo-web` and `mnemo-feishu`, and verified the public tunnel health endpoint. |

### Testing

- [OK] `.venv/bin/python -m unittest tests.test_channels tests.test_cli`
- [OK] `git diff --check`
- [OK] `rg -n "正在思考" mnemo tests .trellis/spec README.md` returned no matches.
- [OK] Restarted `mnemo-web` and `mnemo-feishu`; `https://mem.day.qzz.io/api/health` returned `ok: true`, and Feishu websocket connected.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


### Git Commits

| Hash | Message |
|------|---------|
| `e28ad3c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
