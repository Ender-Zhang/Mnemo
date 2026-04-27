# HTTP Core API Foundation

## Goal
Expose the existing MnemoCore SDK contract over a dependency-free HTTP JSON surface so non-Python clients can call the same compact context, recall, capsule, run, replay, evaluate, and external runtime methods.

## Requirements
- Reuse `MnemoClient` and existing runtime services; do not introduce a second workflow.
- Add HTTP JSON endpoints for API schema, OpenAPI-style discovery, and core method calls.
- Keep results compact and consistent with SDK/CLI/MCP payloads.
- Normalize expected request and service errors as JSON without Python tracebacks.
- Add a CLI entrypoint to serve the HTTP API using the existing stdlib web server.
- Update integration specs, README, design/checklist, and package smoke coverage.

## Acceptance Criteria
- [x] `GET /api/core/schema` returns `mnemo.core_api.v1`.
- [x] `GET /api/core/openapi.json` returns a compact OpenAPI 3.1 document for core methods.
- [x] `POST /api/core/<method>` dispatches to the matching `MnemoClient` method for `context`, `recall`, `capsule`, `run`, `replay`, `evaluate`, and `external-run`.
- [x] Invalid JSON, unknown methods, and service validation failures return JSON errors with appropriate status codes.
- [x] `mnemo api serve` starts the HTTP API server with host/port/state-dir controls.
- [x] Tests cover schema, OpenAPI discovery, method dispatch, error handling, CLI parser, and package smoke import.

## Technical Notes
- The HTTP layer is a thin transport over `MnemoClient`.
- Provider-backed streaming chat remains in the existing `/api/chat` web route; core API `run` mirrors SDK/local behavior.
- `external-run` accepts an explicit command array; no shell string execution.
