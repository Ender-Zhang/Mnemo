# Implement File Patch Tool

## Goal

Add a lightweight patch-specialized workspace tool so the model can make bounded text edits without falling back to shell commands or full-file overwrites.

## Scope

- Add a provider-native `file_patch` tool spec.
- Keep the tool workspace-scoped and admin-gated.
- Apply exact text replacements to UTF-8 files only.
- Reject missing or ambiguous replacement text unless `replace_all=true`.
- Return compact patch result metadata and evidence.
- Cover success, policy denial, path traversal, and ambiguity with tests.
- Update tool harness specs and implementation checklist.

## Acceptance

- [x] `file_patch` appears in standard tool specs and handler registry.
- [x] Admin policy can apply exact replacements to a workspace text file.
- [x] Default policy denies `file_patch`.
- [x] Path traversal is rejected.
- [x] Ambiguous replacement text is rejected unless `replace_all=true`.
- [x] Focused and full unit suites pass.
- [x] Changes are committed locally.
