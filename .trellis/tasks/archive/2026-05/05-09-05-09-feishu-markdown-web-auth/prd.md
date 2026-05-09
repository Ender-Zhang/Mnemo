# Feishu Markdown And Web Auth

## Goal
Feishu replies should render structured Markdown-like content instead of plain text, and the public web UI should require a password before access.

## Requirements
- Convert Mnemo assistant Markdown replies into Feishu/Lark post content so headings, bullets, links, code, and quotes display cleanly.
- Keep Feishu fallback behavior safe when the reply is empty or contains unsupported Markdown.
- Add password protection for the web frontend and API routes exposed through `mnemo web`.
- Make the password configurable without committing secrets, and allow local tests to run without a password by default.
- Avoid logging or returning the raw password.
- Keep `mem.day.qzz.io` reachable after restart, but require the configured password for browser access.

## Acceptance Criteria
- Feishu channel sends post/rich-text replies for Markdown content instead of plain text-only messages.
- Web requests without an authenticated session get a login page or JSON 401, not the app shell or protected API data.
- A valid password creates a session cookie and allows normal Web UI/API access.
- Tests cover Markdown conversion and Web auth success/failure.
- `https://mem.day.qzz.io/api/health` stays OK after deployment restart.
- Git commit and push completed.
