# MCP Content Length Transport

## Goal
Make Mnemo's existing MCP-style JSON-RPC server usable by standard MCP stdio clients by adding `Content-Length` message framing.

## Requirements
- Keep the existing dependency-free MCP server and JSON-RPC handlers.
- Add binary stdio framing with `Content-Length: <bytes>\r\n\r\n<json>`.
- Preserve JSONL serve mode for tests and simple local debugging.
- Add CLI transport selection for `mnemo mcp serve`.
- Keep structured JSON-RPC errors for parse/framing/tool failures.
- Avoid external dependencies and database changes.

## Acceptance Criteria
- [x] `MnemoMcpServer` can read and write MCP Content-Length framed messages.
- [x] `mnemo mcp serve` defaults to Content-Length framing and can opt into JSONL.
- [x] Framing tests cover initialize/list/call and parse/framing errors.
- [x] CLI tests cover Content-Length serve and JSONL serve.
- [x] API schema/checklist/backend integration docs reflect the new transport.
- [x] Package smoke still imports the MCP server.

## Technical Notes
- This is transport work only; tool descriptors and tool behavior should remain unchanged.
- Full external packaging/installer metadata remains a separate task.
