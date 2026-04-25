# Decision cards for denied high-risk tools

## Goal
When the model calls an external/admin tool that the current policy does not allow, Mnemo should create a compact persisted Decision Card instead of only failing silently. This keeps permission control lightweight while giving the user a clear inline approval surface.

## Requirements
- Keep the existing policy gate: denied tools must not execute.
- For denied `external` and `admin` tools, create an Inbox decision item with compact tool name, risk, call id, and bounded arguments.
- Return a compact `ToolResult` containing the decision metadata and no raw schemas or large payloads.
- Stream a `decision.card` for denied high-risk tools using the existing frontend card path.
- Preserve existing `tool.denied`, `tool.result`, and tool-call persistence.
- Do not implement standing authority or approved replay execution in this task.

## Acceptance
- [x] Disallowed external/admin calls create Inbox decisions and emit decision cards.
- [x] Disallowed write/read calls that are not high-risk keep the existing denial behavior.
- [x] Compact evidence and result payloads do not expose internal SQLite fields or raw schemas.
- [x] Web replay/resolution works with the generated decision item.
- [x] Specs and checklist describe the implemented foundation and remaining limits.
