# MCP Config Packaging Foundation

## Goal
Expose a small, dependency-free MCP server configuration generator so external MCP clients can connect to Mnemo without hand-writing stdio command wiring.

## Requirements
- Add an importable MCP config helper under `mnemo.mcp`.
- Add `mnemo mcp config` with JSON output for generic and Claude-style MCP client snippets.
- Keep output compact, deterministic, and secret-free.
- Reuse the existing `mnemo mcp serve` command and current tool descriptor registry.
- Do not add a new runtime workflow, daemon mode, or provider-specific behavior.

## Acceptance Criteria
- [x] `mnemo mcp config --client generic --state-dir DIR --json` returns command, args, transport, tool count, and tool names.
- [x] `mnemo mcp config --client claude --state-dir DIR --json` returns a `mcpServers.mnemo` snippet backed by `mnemo mcp serve`.
- [x] Direct Python import exposes the same helper for package consumers.
- [x] CLI, MCP unit tests, and package install smoke cover the new surface.
- [x] README, checklist, and backend integration contracts describe the config packaging foundation.

## Technical Notes
- This is packaging metadata only. It must not start a server, mutate state, or execute external clients.
- `state_dir` is included as explicit CLI args so client config stays portable and visible.
- Tool names are listed as compact discovery, but raw tool schemas are not embedded in the config.
