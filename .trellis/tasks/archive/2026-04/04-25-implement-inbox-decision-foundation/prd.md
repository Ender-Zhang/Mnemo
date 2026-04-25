# Implement Inbox Decision Foundation

## Goal
Add the first lightweight Inbox/Decision persistence slice so model-created decision requests are durable, inspectable, resolvable, and usable from the single-chat UI.

## Requirements
- Add an idempotent SQLite migration for Inbox items.
- Expose storage APIs to create, list, read, and resolve Inbox items without leaking unrelated run payloads.
- Persist `ask_user` tool calls as open decision Inbox items and include the item id in compact tool results and `decision.card` events.
- Add CLI inspection and resolution commands for pending/all Inbox items.
- Add Web JSON APIs for listing and resolving Inbox items.
- Upgrade the existing frontend decision card from a static card to compact inline approve/reject/ignore actions.
- Keep the system lightweight: no workflow router, no blocking approval engine, no high-risk automation execution yet.
- Update checklist and backend/frontend specs.

## Acceptance Criteria
- [x] Fresh and migrated state dirs have an `inbox_items` table with schema version updated.
- [x] `StateStore` can add/list/get/resolve Inbox items with JSON action data.
- [x] `ask_user` creates a persistent `decision` Inbox item and emits compact `decision.card` data.
- [x] `mnemo inbox list/show/resolve` works in text and JSON modes with normalized missing-id errors.
- [x] Web `GET /api/inbox` and `POST /api/inbox/resolve` work and return JSON errors for invalid input.
- [x] Frontend decision cards render actions and call the resolve API without leaving the single chat surface.
- [x] Tests cover storage migration/API, tool projection, CLI, Web API, and frontend asset hooks.

## Validation
- `.venv/bin/python -m unittest tests.test_storage tests.test_tools tests.test_cli tests.test_web`
- `.venv/bin/python -m unittest discover -s tests`
- `.venv/bin/python -m mnemo harness smoke`
- `python3 ./.trellis/scripts/task.py validate 04-25-implement-inbox-decision-foundation`
- `git diff --check`

## Technical Notes
- This task only records and resolves decisions; it does not execute approved high-risk actions or implement standing authority.
- Action data must stay structured JSON and compact.
