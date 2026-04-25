# Tighten Web Fetch URL Validation

## Goal
Make `web_fetch` reject malformed HTTP/HTTPS URLs before handing them to urllib so tool failures are deterministic, compact, and consistent with connector URL validation.

## Requirements
- Reuse the existing standard-tool HTTP URL validator.
- Reject URLs without an HTTP/HTTPS scheme or without a network location.
- Preserve the existing successful `web_fetch` payload shape.
- Add regression coverage in standard tool tests.
- Update the tool harness contract and implementation checklist.

## Acceptance Criteria
- [x] `web_fetch` rejects malformed URLs such as `https:///missing-host`.
- [x] Failed malformed URL calls return a failed `ToolResult` with compact tool-error evidence.
- [x] Existing browser/app connector behavior is unchanged.
- [x] Relevant unit tests and Trellis validation pass.

## Technical Notes
- This is a tool input validation hardening task, not a new workflow or new tool.
- Do not broaden permissions or add routing logic.
