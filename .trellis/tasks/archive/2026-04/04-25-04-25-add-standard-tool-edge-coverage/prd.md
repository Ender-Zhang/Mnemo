# Add Standard Tool Edge Coverage

## Goal

Close the remaining tool-harness edge coverage gaps for local standard tools without adding new workflow logic.

## Requirements

- Add a focused test that `file_read` rejects binary files and does not return decoded text.
- Add a focused test that `shell_exec` reports command timeout as a failed tool result.
- Keep tests deterministic and local.
- Update the tool-harness validation matrix to point at the concrete test file.

## Acceptance Criteria

- [x] Binary file reads return `ToolResult(ok=False)` with a binary-file error.
- [x] Shell command timeout returns `ToolResult(ok=False)` with a timeout error.
- [x] Standard tool focused tests pass.
- [x] Full unit tests pass.
- [x] Trellis task validation passes.
- [x] Changes are committed locally.

## Technical Notes

- Prefer existing `ToolHarness` behavior; change implementation only if the tests reveal a real bug.
- Use `sys.executable` for timeout tests so the command is portable across developer machines and CI.
