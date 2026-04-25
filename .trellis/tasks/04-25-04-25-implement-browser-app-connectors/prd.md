# Implement Browser App Connectors

## Goal

Add the smallest useful browser/app connector layer to the existing provider-native tool surface so the model can hand work off to the user's default browser or local app when needed.

## Requirements

- Add `browser_open` as an external-risk tool for opening HTTP/HTTPS URLs in the default browser.
- Add `app_open` as an admin-risk tool for opening workspace-scoped files or folders with the OS default app.
- Keep both tools normal `ToolSpec` entries handled by `ToolHarness`; do not add routing, workflows, or browser automation dependencies.
- Keep tool results compact and evidence-card friendly.
- Preserve workspace path scoping for local app opens.
- Update tool-harness spec and implementation checklist.

## Acceptance Criteria

- [x] `ToolRegistry().specs()` includes `browser_open` and `app_open`.
- [x] Default policy denies both connector side-effect tools unless their risk is allowed.
- [x] `browser_open` validates URL scheme and supports a testable dry-run path.
- [x] `app_open` rejects path traversal and supports a testable dry-run path.
- [x] Connector results have compact summary/evidence.
- [x] Focused and full unit tests pass.
- [x] Trellis task validation passes.
- [x] Changes are committed locally.

## Technical Notes

- Use stdlib only.
- Use platform opener commands only when `dry_run=false` and the tool risk is explicitly allowed.
- `browser_open` complements `web_fetch`: fetch reads page content, open hands a URL to the user-facing browser.
- `app_open` complements file tools: file tools inspect/edit content, open hands a local artifact to the user's OS app.
