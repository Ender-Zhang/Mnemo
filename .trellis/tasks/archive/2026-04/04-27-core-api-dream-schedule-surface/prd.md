# Core API Dream Schedule Surface

## Goal
Expose Dream scheduled-maintenance registration through the language-neutral MnemoCore SDK/HTTP API while keeping scheduling and memory decisions inside existing services.

## Requirements
- Add a compact `MnemoClient.schedule_dream()` method backed by `ScheduleService.add_dream()`.
- Add `schedule_dream` to `mnemo.core_api.v1` schema and OpenAPI discovery.
- Add HTTP transport `POST /api/core/schedule-dream` as a thin dispatcher over `MnemoClient`.
- Preserve compact payloads and avoid raw memory/report bodies.
- Keep CLI/MCP/scheduler behavior unchanged.
- Update specs, design docs, checklist, and tests.

## Acceptance Criteria
- [x] SDK can create a Dream scheduled item with default daily schedule and explicit budget fields.
- [x] Core API schema and CLI schema output include `schedule_dream`.
- [x] HTTP `/api/core/schedule-dream` creates a compact Dream scheduled item and appears in OpenAPI.
- [x] Invalid HTTP `next_run_at` payloads are normalized as JSON errors without traceback.
- [x] Specs/checklist/design docs describe the new API surface as a thin transport, not a workflow.

## Technical Notes
- This task does not add remote generated clients.
- This task does not add a new Dream execution endpoint; due execution remains `ScheduleService.tick()`.
