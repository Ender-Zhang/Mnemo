# Implement Cross Client Skill Roots

## Goal

Make the skill scanner discover mainstream Agent Skills roots without requiring users to pass every path manually.

## Scope

- Extend default skill root discovery beyond Mnemo-owned roots.
- Include workspace-local Claude, Hermes, and OpenClaw skill roots.
- Include user-home Claude, Hermes, and OpenClaw skill roots.
- Keep root ordering deterministic and de-duplicated.
- Preserve explicit `--root` overrides as additive.
- Cover default roots and scan behavior with tests.
- Update checklist and skill-evolution specs.

## Acceptance

- [x] `default_skill_roots()` includes state, `.mnemo`, `.agents`, Claude, Hermes, and OpenClaw roots.
- [x] Duplicate roots are removed while preserving first-seen order.
- [x] `skills scan` can import skills from one of the mainstream roots without `--root`.
- [x] Explicit roots still append to default roots.
- [x] Focused and full unit suites pass.
- [x] Changes are committed locally.
