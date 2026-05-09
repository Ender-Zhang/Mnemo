# Settings Standalone Page

## Goal
Settings should behave like Memory, Skills, and Tools: a normal standalone view in the main shell instead of a drawer or mobile bottom sheet.

## Requirements
- Remove settings drawer/sheet activation logic from the web client.
- Remove the settings close button and backdrop markup.
- Keep the existing settings forms, Feishu onboarding controls, and `/api/settings` behavior unchanged.
- Keep hash navigation working with `#settings`.
- Update CSS so settings uses the full page layout on desktop and mobile.
- Update web asset tests to assert standalone settings behavior.

## Acceptance Criteria
- Clicking Settings activates only the settings view and does not keep chat visible underneath.
- The HTML/CSS/JS no longer reference settings drawer/sheet classes or close controls.
- `tests.test_web` passes.
- Local `mnemo-web` is restarted and `mem.day.qzz.io` reflects the change.
- Git commit and push completed.
