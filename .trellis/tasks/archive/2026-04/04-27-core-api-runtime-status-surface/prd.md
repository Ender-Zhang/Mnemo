# Core API Runtime Status Surface

## Goal
Expose the existing compact runtime status surface through MnemoCore SDK and HTTP so language-neutral integrations can inspect queue, runs, inbox, generated tools, and scheduled items without using MCP.

## Requirements
- Add `MnemoClient.runtime_status(limit=10)` as a read-only compact status method.
- Route MCP `mnemo_runtime_status` through the SDK method to avoid duplicated integration logic.
- Add `runtime_status` to `mnemo.core_api.v1` schema and OpenAPI discovery.
- Add HTTP `POST /api/core/runtime-status` as a thin dispatcher over `MnemoClient`.
- Keep payloads compact and free of raw run bodies, traces, prompt content, or artifact bodies.
- Update specs, design docs, checklist, and tests.

## Acceptance Criteria
- [x] SDK returns compact runtime status with queue, recent run cards, open inbox cards, generated tool counts, and scheduled stats.
- [x] MCP runtime status still returns the same compact status shape via the SDK path.
- [x] Core API schema and CLI schema output include `runtime_status`.
- [x] HTTP `/api/core/runtime-status` returns compact status and appears in OpenAPI.
- [x] Specs/checklist/design docs describe runtime status as a read-only transport surface.

## Technical Notes
- This task does not add a supervisor workflow or runtime cleanup.
- This task does not expose raw run input/output bodies; run cards stay preview-only.
