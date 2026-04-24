# Implement Skills Metadata Compatibility

## Goal

Improve Agent Skills compatibility by preserving common `SKILL.md` frontmatter metadata in compact indexes while keeping full skill bodies behind `skill_view`.

## Scope

- Parse `allowed-tools` and `allowed_tools` list variants.
- Parse simple `arguments` metadata maps/lists.
- Preserve compact `scope`, `path`, and `source` metadata in skill cards.
- Keep scanning deterministic and lightweight.
- Add regression tests for parser and compact cards.

## Non-Goals

- No skill execution harness.
- No workflow router or automatic skill invocation.
- No generated skill eval lifecycle.
