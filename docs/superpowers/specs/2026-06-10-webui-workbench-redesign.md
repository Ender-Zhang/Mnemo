# Mnemo WebUI Workbench Redesign

Date: 2026-06-10

## Goal

Mnemo WebUI should feel like a user-friendly local memory management console, not a debug dashboard. The first screen should make three actions obvious:

- Search a user's memories.
- Inspect one memory and understand where it came from.
- Save a new memory.

Advanced memory-service operations should remain available, but they should no longer compete with the primary user workflow. Candidate review, Dream runs, tombstones, raw JSON, links, and audit details move behind an advanced mode.

## Current Problem

The current WebUI exposes too many operational surfaces at the same visual level:

- Left navigation has overview, memories, candidates, tombstones, maintenance, and settings.
- Main content has another tab row that duplicates navigation.
- The page always shows memory list, detail panel, composer, and operations queue together.
- Dream status, JSON blocks, candidate actions, tombstones, and provenance are mixed into normal memory browsing.
- A new user cannot easily tell whether the primary path is search, write, review, or maintain.

The result is powerful but cognitively noisy.

## Design Direction

Use one application with two modes:

- Default mode: a memory workbench for normal use.
- Advanced mode: the same workbench with service internals exposed.

This avoids maintaining two separate applications while still giving new users a calm default experience.

## Information Architecture

### Default Mode

Default navigation should have only three primary destinations:

1. Memory Workbench
2. Model & Maintenance
3. Settings

Memory Workbench is the default landing page. It contains:

- Service/token status in the top bar.
- Current user scope selector.
- Search box.
- Memory list with stable memories first.
- Detail panel with readable content and provenance timeline.
- Primary action button: Save Memory.

The default mode hides:

- Candidate queue as a separate navigation item.
- Tombstones as a separate navigation item.
- Raw JSON blocks.
- Low-level link dumps.
- Dream report JSON.
- Manual promote/reject buttons, unless shown as a compact "needs review" state.

### Advanced Mode

Advanced mode is enabled with a visible switch in the sidebar or top bar.

When enabled, the UI exposes:

- Candidate Review
- Dream Runs
- Tombstones / Deletion
- Raw JSON / Evidence
- Links
- Audit result details
- Source ids such as `run_id`, `source_candidate_id`, `message_id`, and `raw_hash`

Advanced mode should preserve the same selected memory and search state. Toggling the mode should not reset the page.

## Page Structure

### Shell

The shell remains a sidebar plus main workspace, but the tab row inside the workspace should be removed. Navigation should exist in one place only.

Top bar should show:

- Service status: running, token missing, or offline.
- API base.
- Current token state.
- Refresh button.
- Advanced mode switch.

### Memory Workbench

Memory Workbench uses a three-area layout on desktop:

1. Left sidebar: app navigation.
2. Center: search, filters, memory list.
3. Right: selected memory detail.

The current always-visible write composer should be replaced by a Save Memory drawer or modal. This keeps the default screen focused on browsing and retrieval.

Memory list items should show:

- Human-readable title or claim.
- Type badge: stable memory or candidate.
- Scope/user.
- Confidence.
- Last updated time.
- Provenance count when available.
- Review state only when relevant.

Detail panel should show, in default mode:

- Memory content.
- Status and confidence.
- Scope/user.
- Updated time.
- Source timeline: event -> candidate -> stable memory.
- Simple actions: copy, tombstone/delete, edit later if supported.

Detail panel should show, in advanced mode:

- Audit result and gate reason.
- Raw metadata/evidence.
- Links.
- Source ids.
- Tombstone/forget controls with explicit reason input.

### Save Memory Drawer

The Save Memory drawer should guide the user through one clear action:

- User scope.
- Fact text.
- Observation text.
- Source.
- Submit.

After submission, the drawer should show the generated candidates in plain language:

- Saved as candidate.
- Needs model review.
- Already duplicate.
- Blocked by safety/quality.

If advanced mode is off, keep this summary short. If advanced mode is on, allow expanding the raw response.

### Model & Maintenance

Default mode should present model and maintenance as status plus simple actions:

- Provider configured or not.
- Use model review toggle.
- Last Dream run.
- Run maintenance now.
- Auto Dream status.

Advanced mode adds:

- Dream run report details.
- Review/reject reasons.
- Snapshot JSON.
- Health cards.
- Action counts and skipped actions.

### Settings

Settings should remain the home for:

- API base.
- Bearer token local storage.
- Provider config.
- Auto Dream config.
- Default source.

Default mode should keep labels clear and hide raw config unless expanded.

## Data Flow

### Search Flow

1. User selects or enters a user scope.
2. User types a query.
3. WebUI calls `POST /api/memory/search`.
4. Center list shows ranked matches.
5. Selecting an item calls `read`, `links`, and `provenance`.
6. Detail panel renders content and readable source timeline.
7. Advanced mode optionally reveals raw evidence and link data.

### Save Flow

1. User clicks Save Memory.
2. Drawer collects fact, observation, source, and scope.
3. WebUI calls `POST /api/memory/update`.
4. API writes source events and memory candidates.
5. UI shows a candidate summary.
6. If model review is enabled, user can run Dream from the summary or Model & Maintenance page.
7. Promoted candidates appear as stable memories in search/list results.

### Advanced Review Flow

1. User enables advanced mode.
2. Candidate Review appears in navigation.
3. Candidate rows show quality, safety, confidence, duplicate/conflict hints, and model review results.
4. User can manually promote/reject, but this is presented as an operator action.
5. Dream model review remains the recommended path for non-manual review.

## Error Handling

The UI should use plain-language empty and error states:

- No token: "请输入本地服务 token 后再调用 API。"
- Offline: "服务未连接，请确认 mnemo-memory serve 正在运行。"
- No memories: "还没有稳定记忆，可以先保存一条事实或观察。"
- No source timeline: "这条记忆没有来源事件，可能来自旧数据。"
- Provider missing: "尚未配置模型，Dream 将只生成报告，不会执行模型审核。"

Technical error details can be expandable in advanced mode.

## Responsive Behavior

Desktop:

- Sidebar + center list + detail panel.

Tablet:

- Sidebar collapses.
- Center list and detail panel remain side-by-side if space allows.

Mobile:

- Single column.
- Memory list opens detail as a full-screen panel.
- Save Memory opens a full-screen drawer.
- Advanced mode keeps navigation compact and avoids three-column layouts.

## Implementation Boundaries

This redesign should not change backend API behavior. It is a WebUI reorganization around existing endpoints.

Expected frontend changes:

- Add `advancedMode` state with localStorage persistence.
- Simplify `navItems` based on mode.
- Remove duplicate workspace tab row.
- Replace always-visible `Composer` panel with a drawer/modal.
- Split detail rendering into default and advanced sections.
- Move operations queue behind advanced mode.
- Adjust CSS for calmer default layout and mobile stacking.

Backend changes are not required unless the UI discovers missing metadata during implementation.

## Acceptance Criteria

- First load shows Memory Workbench, not a mixed operations dashboard.
- A new user can search, select, inspect provenance, and save memory without seeing raw JSON.
- Advanced mode exposes candidates, Dream runs, tombstones, links, evidence, and audit details.
- Switching advanced mode does not lose current search, selected memory, or input state.
- Save Memory is available as one clear primary action.
- Mobile layout has no overlapping text or inaccessible controls.
- Existing auth/token flow still works.
- Existing API calls remain compatible.

## Test Plan

Frontend:

- `npm --prefix webui run build`
- Existing WebUI tests, if present.
- Add focused tests for advanced-mode navigation filtering if feasible.

Browser QA:

- Start `mnemo-memory serve --auth-token dev-token`.
- Open WebUI.
- Verify default mode:
  - token entry works.
  - search/list/read works.
  - provenance timeline is readable.
  - Save Memory drawer submits update.
  - raw JSON is hidden.
- Verify advanced mode:
  - candidate review appears.
  - Dream run controls appear.
  - tombstone controls appear.
  - raw evidence/links are visible.
- Check desktop and narrow mobile widths.
