# Implement Standard Local Tools Foundation

## Goal
Give the agent a compact, provider-native tool surface for common task execution while keeping risky capabilities policy-gated.

## Requirements
- Add built-in local tools for workspace file search and file read.
- Add policy-gated tools for workspace file write, HTTP fetch, and shell execution.
- Keep all path-based file operations scoped to the configured workspace root.
- Keep shell execution list-based and non-shell by default.
- Return compact summaries and evidence cards so tool results stay cheap to feed back to the model.
- Preserve the existing provider-native tool loop: the model decides when and how to call tools.

## Acceptance Criteria
- [x] `file_search` and `file_read` work with the default read/write policy.
- [x] `file_write`, `web_fetch`, and `shell_exec` are denied by the default policy.
- [x] Path traversal outside the workspace root is blocked.
- [x] Explicit policy can enable an admin tool without changing the registry.
- [x] Unit tests cover allowed reads, denied risky tools, path scoping, and shell command execution under explicit policy.

## Technical Notes
- This is a backend runtime/tooling change.
- No frontend changes are expected.
- Do not introduce a workflow router; expose tools and let the provider tool loop decide.
