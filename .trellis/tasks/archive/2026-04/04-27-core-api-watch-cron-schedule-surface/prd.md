# Core API Watch Cron Schedule Surface

## Goal
Expose the existing Watch and Cron scheduled-item registration surfaces through MnemoCore SDK and HTTP so language-neutral integrations can register proactive checks and queued recurring tasks without using MCP or CLI-only paths.

## Requirements
- Add `MnemoClient.schedule_watch(...)` as a compact facade over `ScheduleService.add_watch()`.
- Add `MnemoClient.schedule_cron(...)` as a compact facade over `ScheduleService.add_cron()`.
- Add `schedule_watch` and `schedule_cron` to `mnemo.core_api.v1` schema and compact OpenAPI discovery.
- Add HTTP `POST /api/core/schedule-watch` and `POST /api/core/schedule-cron` as thin dispatchers over `MnemoClient`.
- Keep Watch/Cron execution semantics unchanged: registration only; due processing remains scheduler/daemon driven.
- Update specs, design docs, checklist, package smoke, and tests.

## Acceptance Criteria
- [x] SDK registers Watch items with target, instruction, schedule, source, due time, and compact metadata.
- [x] SDK registers Cron items with message, optional title, schedule, source, due time, and compact metadata.
- [x] Core API schema and CLI schema output include `schedule_watch` and `schedule_cron`.
- [x] HTTP `/api/core/schedule-watch` and `/api/core/schedule-cron` return compact scheduled item payloads and appear in OpenAPI.
- [x] Invalid HTTP Watch/Cron payloads return compact JSON errors without tracebacks.
- [x] Specs/checklist/design docs describe Watch/Cron Core API registration as a thin transport over the existing scheduler.

## Technical Notes
- This task does not add full cron expression parsing, Sense triggers, delivery channels, or scheduler execution changes.
- This task does not run scheduled work directly; it only exposes registration through the existing SDK/HTTP contract.
