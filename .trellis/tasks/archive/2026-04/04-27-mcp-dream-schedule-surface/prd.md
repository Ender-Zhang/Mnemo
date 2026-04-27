# MCP Dream Schedule Surface

## Goal
Expose the existing Dream scheduled-maintenance foundation through the MCP tool surface so external agents can register daily or one-shot memory maintenance without using the CLI.

## Requirements
- Add a compact `mnemo_dream_schedule` MCP tool descriptor.
- Route the tool through `ScheduleService.add_dream()`; do not create a new scheduling or memory workflow.
- Preserve compact payloads: budget fields, scheduled item metadata, and runtime status only.
- Keep `mnemo_watch` and `mnemo_cron` behavior unchanged.
- Update integration specs, checklist, and tests.

## Acceptance Criteria
- [x] MCP tool listing includes `mnemo_dream_schedule` with write risk and compact schema.
- [x] Direct MCP calls can create daily and one-shot Dream scheduled items.
- [x] Due one-shot Dream items can be ticked through existing scheduler behavior and are visible in runtime status.
- [x] CLI `mnemo mcp call` can create a Dream scheduled item with normalized JSON handling.
- [x] Specs and checklist reflect MCP Dream registration.

## Technical Notes
- Dream scheduling remains a trigger/budget surface. Memory decisions stay inside `MemoryEngine.dream_maintenance()`.
- MCP should mirror CLI defaults: omitted schedule means `daily`, bounded limit/min-confidence are handled by `ScheduleService`.
