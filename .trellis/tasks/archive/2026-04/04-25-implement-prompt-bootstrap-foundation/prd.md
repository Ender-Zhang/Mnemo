# Implement Prompt Bootstrap Foundation

## Goal
Add the first production slice of Soul/workspace bootstrap prompt context so Mnemo can inject stable user/project context without dumping arbitrary files into every prompt.

## Requirements
- Load user Soul from the configured state directory (`SOUL.md`) when present.
- Load bounded workspace bootstrap files such as `AGENTS.md`, `MNEMO.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, `BOOTSTRAP.md`, `CLAUDE.md`, `.mnemo.md`, `.cursorrules`, and `.cursor/rules/*.mdc`.
- Treat bootstrap files as quoted context that cannot override core system/developer instructions.
- Enforce per-file and total character caps with stable truncation markers.
- Add lightweight injection warnings to prompt metadata without exposing raw file contents there.
- Keep prompt ordering cache-friendly: core stable blocks first, Soul as stable user profile, tool bundle stable, workspace bootstrap as daily context, then dynamic mission/turn context.
- Wire runtime and CLI/Web requests so normal user entrypoints can pass a workspace root.
- Update implementation checklist and prompt specs.

## Acceptance Criteria
- [x] `PromptAssembler` can inject Soul and workspace bootstrap blocks with deterministic ordering.
- [x] Prompt metadata includes block ids/sources/token estimates but not raw Soul/bootstrap content.
- [x] Runtime persists prompt metadata showing bootstrap blocks when files are present.
- [x] CLI/Web run requests carry a workspace root for bootstrap discovery.
- [x] Existing prompt budgeting behavior remains compatible.
- [x] Tests cover Soul loading, workspace bootstrap caps/truncation, runtime injection, and prompt inspect behavior.

## Validation
- `.venv/bin/python -m unittest tests.test_prompt tests.test_runtime tests.test_cli tests.test_web`
- `.venv/bin/python -m unittest discover -s tests`
- `.venv/bin/python -m mnemo harness smoke`
- `python3 ./.trellis/scripts/task.py validate 04-25-implement-prompt-bootstrap-foundation`
- `git diff --check`

## Technical Notes
- This task does not implement Soul self-evolution, user confirmation flows, or full prompt cache provider integration.
- Workspace bootstrap should remain optional and bounded; absence of files must preserve current prompt behavior.
