# MCP Server Foundation

## Goal
Expose Mnemo's core agent surfaces through a lightweight MCP-style integration layer so external clients can list and call compact tools without depending on internal modules.

## Requirements
- Provide MCP-style tool descriptors for context, update, recall, search, skills, tools, run, replay, eval, runtime status, watch, and cron.
- Route tool calls through existing SDK/service boundaries where possible.
- Keep payloads compact and cache-friendly; avoid exposing raw traces, evidence blobs, or full tool schemas by default.
- Support JSON-RPC handlers for `initialize`, `tools/list`, and `tools/call`.
- Add CLI commands to list tools, call tools, and serve the JSON-RPC stdio foundation.
- Avoid new external dependencies and avoid database migrations.

## Acceptance Criteria
- [x] MCP-style tool descriptors include input schemas and read/write annotations.
- [x] Direct tool calls cover context/update/recall/search/skills/tools/run/replay/eval/status.
- [x] Watch and cron calls expose explicit lightweight placeholders until persistence is implemented.
- [x] JSON-RPC handlers return valid results and structured errors.
- [x] CLI supports `mnemo mcp tools`, `mnemo mcp call`, and `mnemo mcp serve`.
- [x] Tests cover direct calls, JSON-RPC, CLI behavior, and package import smoke.
- [x] Implementation checklist and backend integration specs reflect the new foundation.

## Technical Notes
- Use existing `MnemoClient` for context, recall, run, replay, and evaluate.
- Use `MemoryEngine`, `SkillService`, `ToolRegistry`, and `StateStore` directly only for surfaces not yet covered by the SDK.
- Keep transport framing intentionally minimal in this iteration: JSON lines over stdio, not full Content-Length MCP framing.
