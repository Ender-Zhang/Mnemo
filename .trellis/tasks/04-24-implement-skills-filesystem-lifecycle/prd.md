# Implement Skills Filesystem Lifecycle

## Goal

Make Mnemo skills compatible with mainstream Agent Skills operations while supporting generated skill promotion into real `SKILL.md` files.

## Requirements

- Add skill filesystem scanner for configured roots.
- Support Agent Skills-style directories containing `SKILL.md`.
- Parse minimal frontmatter fields: `name`, `description`, `allowed-tools`, and Mnemo metadata when present.
- Add skill service for listing scanned skills, viewing skill bodies, and promoting draft skill rows into generated `SKILL.md` files.
- Keep external skill roots read-only by default.
- Add CLI commands for `skills scan`, `skills list`, `skills view`, and `skills promote`.
- Existing `skills_list` / `skill_view` tools should include filesystem skills.
- Add tests with temporary skill roots.

## Acceptance Criteria

- `.agents/skills/*/SKILL.md` can be scanned and listed.
- A draft skill proposal can be promoted to `<state_dir>/skills/_generated/<name>/SKILL.md`.
- `mnemo skills view <name>` returns the skill body.
- Tests pass without network access.
