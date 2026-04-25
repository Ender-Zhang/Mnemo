# Refresh README Current Capabilities

## Goal
Bring the repository README up to date with the current Mnemo implementation so a user or agent can start, run, inspect, and validate the system without reading source code first.

## Requirements
- Describe Mnemo as the current agentic runtime implementation, not only a design package or first backend slice.
- Cover local turns, provider-backed turns, web chat, daemon queue, run cancellation, memory/skills/tools inspection, backup, and harness validation.
- Keep commands concise, copyable, and free of secrets.
- Keep README aligned with the root `mnemo/` package layout and package smoke contract.
- Update `IMPLEMENTATION_CHECKLIST.md` to record the landed docs work.

## Acceptance Criteria
- [x] README documents current capabilities and primary entrypoints.
- [x] README includes local, provider, web, daemon, and validation commands.
- [x] README avoids stale wording about the implementation being only a first deterministic slice.
- [x] Checklist includes the landed documentation refresh.
- [x] Documentation diff passes whitespace checks and unit tests still pass.

## Technical Notes
- This is a documentation and metadata task. Do not change runtime behavior.
- Do not include real provider credentials in docs.
- Prefer short sections over a large architecture essay.
