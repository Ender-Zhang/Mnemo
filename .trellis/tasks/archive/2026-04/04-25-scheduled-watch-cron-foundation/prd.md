# Scheduled Watch Cron Foundation

## Goal
Add a lightweight persistence and processing foundation for Watch/Cron so proactive requests can be registered durably and converted into normal Mnemo daemon queue work.

## Requirements
- Store watch and cron registrations in SQLite with compact metadata, status, schedule string, and next due time.
- Keep one shared scheduled-item model instead of separate workflow-heavy watch and cron systems.
- Process due items by enqueueing existing daemon run requests with source metadata.
- Support simple built-in schedules without external dependencies.
- Expose storage/service behavior through CLI and MCP surfaces.
- Keep watch/cron execution model-driven: the scheduled run message asks the existing runtime/model to decide what to do.

## Acceptance Criteria
- [x] Fresh and migrated state dirs contain scheduled item storage.
- [x] Storage APIs can add, list, pause/resume/disable, and inspect scheduled items.
- [x] Scheduler service enqueues due items and advances or completes their schedule.
- [x] CLI can add/list/tick scheduled items with normalized errors.
- [x] MCP `mnemo_watch` and `mnemo_cron` create durable scheduled items instead of placeholders.
- [x] Runtime status includes compact scheduled-item status.
- [x] Tests cover storage, scheduler, CLI, MCP, and package smoke compatibility.
- [x] Checklist and backend specs reflect the foundation.

## Technical Notes
- Use existing `run_queue` for actual execution; scheduled items only create due run requests.
- Supported schedule grammar is intentionally small: `once`, `at:<unix-or-iso>`, `every:<seconds>`, `every 10m`, `hourly`, `daily`, and `weekly`.
- Full cron expressions, quiet-hour policy, delivery channels, Watch self-learning, and Sense-triggered watches remain future work.
