# Frontend Redesign Checklist

## Design Assets

- [x] Generate desktop chat UI reference.
- [x] Generate memory drawer UI reference.
- [x] Generate settings drawer UI reference.
- [x] Generate mobile sheet UI reference.
- [x] Save references under `design/assets/frontend-redesign/`.
- [x] Document visual system in `design/12-frontend-visual-system.md`.

## Product Principles

- [x] Preserve one permanent composer as the only primary input.
- [x] Keep Mission/Run technical concepts out of user-facing labels.
- [x] Keep tools visible as compact action cards, not logs.
- [x] Keep memory visible as user continuity, not a database browser.
- [x] Keep settings as a drawer/sheet, not a dashboard.
- [x] Keep mobile behavior aligned with desktop.

## Main Shell

- [x] Replace dark operations-style shell with warm light product shell.
- [x] Make rail compact, icon-like and user-facing: 对话 / 记忆 / 设置.
- [x] Simplify topbar copy and status language.
- [x] Keep timeline centered and readable with stable message widths.
- [x] Make empty state quiet and premium.
- [x] Keep composer visually dominant and fixed at bottom.

## Markdown And Messages

- [x] Stream assistant markdown during deltas.
- [x] Render markdown tables with safe DOM nodes.
- [x] Ensure table styling matches the new visual system.
- [x] Tune user/assistant bubbles to match generated reference.
- [x] Keep pending reply animation visible and subtle.

## Actions And Activity

- [x] Suppress duplicate tool result source cards.
- [x] Compact tool call details.
- [x] Restyle action cards as horizontal action strips.
- [x] Add state-specific visual treatment for queued/running/success/error.
- [x] Restyle right activity rail as a user-facing timeline.
- [x] Keep hidden internal learning events hidden.

## Memory Drawer

- [x] Add `记忆` rail entry.
- [x] Open memory-focused drawer through the existing overlay.
- [x] Fetch `/api/memory/ontology` on open as L1 coverage only.
- [x] Fetch `/api/memory/dimension` after a dimension is selected.
- [x] Fetch `/api/memory/item` after a memory item is selected.
- [x] Use `记忆罗盘` as the user-facing name instead of `十维记忆`.
- [x] Show dimensional coverage rows with bars and counts.
- [x] Show clipped memory summaries first, then evidence rows only after item selection.
- [x] Route update/forget/use actions through composer prefill unless an existing API exists.

## Settings Drawer

- [x] Rewrite settings labels in user-facing Chinese.
- [x] Group sections as 模型 / 工具权限 / 记忆 / Dream / 工作区 / 外观 / 数据.
- [x] Preserve quiet-hours save behavior.
- [x] Never expose provider secrets or raw payloads.
- [x] Include a path from settings to memory drawer.

## Responsive

- [x] Hide context rail below tablet width.
- [x] Turn drawers into full-width/mobile sheets.
- [x] Keep composer usable on mobile.
- [x] Prevent overflow in long ids, URLs, markdown tables and tool payloads.

## Quality Gates

- [x] Update `tests/test_web.py` asset assertions.
- [x] Run `node --check mnemo/interfaces/web_assets/app.js`.
- [x] Run `python -m unittest tests.test_web`.
- [x] Run full `python -m unittest discover -s tests`.
- [x] Run package install smoke for web assets.
- [x] Commit and push.
- [x] Restart the running web service.
