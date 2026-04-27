# Dream Scheduled Maintenance

## Goal
Close the DreamCycle scheduling and L1 refresh gap by letting the existing lightweight scheduler run bounded Dream maintenance during idle/daily windows.

## Requirements
- Reuse `scheduled_items`, `ScheduleService.tick()`, and `MemoryEngine.dream_maintenance()` instead of adding a new background workflow system.
- Add a first-class Dream scheduled item path that supports CLI creation, listing, ticking, and daemon status through existing scheduler surfaces.
- Due Dream items should run Dream maintenance directly, persist a compact Dream report, advance or complete the scheduled item, and report compact tick metadata.
- Dream reports should make L1 snapshot refresh visible through compact execution metadata.
- Existing watch/cron enqueue behavior must remain unchanged.
- Update specs, design docs, checklist, and tests.

## Acceptance Criteria
- [x] A Dream scheduled item can be created with a recurring or one-shot schedule.
- [x] `ScheduleService.tick()` runs due Dream maintenance, persists a Dream report, and advances/completes the item.
- [x] Dream scheduled maintenance compiles a compact L1 snapshot as part of the normal Dream execution path.
- [x] CLI exposes Dream schedule creation and tick output without raw memory bodies.
- [x] Watch/cron scheduler tests continue to pass.
- [x] Specs, design docs, and checklist reflect the new scheduling foundation.

## Technical Notes
- No schema migration is expected if the scheduled item kind validation is widened.
- Dream scheduling is trigger/budget infrastructure; Dream decisions remain model/action-led inside `MemoryEngine`.
