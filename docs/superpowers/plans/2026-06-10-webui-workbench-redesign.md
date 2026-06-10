# WebUI Workbench Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the Mnemo WebUI into a default memory workbench with an advanced mode for debugging and maintenance.

**Architecture:** Keep the existing React + Vite single-page app and Python-backed API unchanged. Rework the app shell, navigation, composer placement, detail visibility, and responsive CSS around the current `MemoryClient` endpoints.

**Tech Stack:** React, TypeScript, Vite, lucide-react, CSS, existing stdlib Python static hosting.

---

## File Map

- Modify `webui/src/main.tsx`: add `advancedMode`, simplify navigation, remove duplicate tabs, add Save Memory drawer, gate advanced panels, and split detail rendering.
- Modify `webui/src/styles.css`: restyle the shell as a calmer workbench, add drawer styles, add advanced-mode responsive behavior, and remove layout pressure from the old three-panel dashboard.
- Modify generated `mnemo_memory/interfaces/web_assets/*`: rebuild WebUI assets after implementation.
- Optionally modify focused WebUI tests only if helper logic is extracted.

## Task 1: Advanced Mode State and Navigation

- [ ] Add `advancedMode` persisted to `localStorage`.
- [ ] Replace static `navItems` usage with `visibleNavItems`, where default mode shows Memory Workbench, Model & Maintenance, Settings.
- [ ] Advanced mode additionally shows Candidate Review and Tombstones / Deletion.
- [ ] Remove the duplicate workspace tab row.
- [ ] Ensure toggling advanced mode does not reset active memory/search state.

Verification:

```bash
npm --prefix webui run build
```

Expected: TypeScript build succeeds.

## Task 2: Save Memory Drawer

- [ ] Replace the always-visible `Composer` in the right column with a `SaveMemoryDrawer`.
- [ ] Add an `isComposerOpen` state and open it from a primary `保存记忆` button in the top bar/workbench.
- [ ] Preserve existing `factText`, `observationText`, `source`, and `submitMemory` behavior.
- [ ] Show the drawer as a side panel on desktop and full-screen panel on narrow screens.

Verification:

```bash
npm --prefix webui run build
```

Expected: TypeScript build succeeds and existing submit behavior is still wired to `submitMemory`.

## Task 3: Default Detail vs Advanced Detail

- [ ] Make `MemoryDetail` accept `advancedMode`.
- [ ] Default mode shows readable content, core metadata, and provenance timeline.
- [ ] Advanced mode shows audit detail, raw metadata/evidence, links, source ids, and destructive tombstone/forget controls.
- [ ] Keep tombstone/forget hidden in default mode except for a plain delete entry point if already selected.

Verification:

```bash
npm --prefix webui run build
```

Expected: TypeScript build succeeds.

## Task 4: Maintenance and Operations Visibility

- [ ] Rename the default maintenance entry to `模型与维护`.
- [ ] Keep provider/Dream status visible in default mode.
- [ ] Move `OperationsQueue`, raw Dream JSON, tombstone bulk operations, and candidate promote/reject controls behind advanced mode.
- [ ] Keep `Run Dream` available in default maintenance as a simple action.

Verification:

```bash
npm --prefix webui run build
```

Expected: TypeScript build succeeds.

## Task 5: CSS Polish and Responsive QA

- [ ] Update `styles.css` so default desktop layout is sidebar + main list + detail, without constant ops/composer columns.
- [ ] Add drawer overlay styles.
- [ ] Keep cards/panels compact with no nested-card visual clutter.
- [ ] Ensure mobile stacks cleanly and text does not overlap.

Verification:

```bash
npm --prefix webui run build
```

Expected: TypeScript build succeeds.

## Task 6: Full Verification

- [ ] Run frontend build.
- [ ] Run existing WebUI tests if available.
- [ ] Run Python tests if backend package data or asset paths changed.
- [ ] Start local service and inspect the WebUI in browser at desktop and mobile widths.
- [ ] Rebuild static assets into `mnemo_memory/interfaces/web_assets/`.

Commands:

```bash
npm --prefix webui run build
npm --prefix webui test -- --run
python3 -m unittest discover -s tests -v
```

Expected: all checks pass, or any unavailable command is reported explicitly.
