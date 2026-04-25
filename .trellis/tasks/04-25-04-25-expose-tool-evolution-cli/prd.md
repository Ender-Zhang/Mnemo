# Expose Tool Evolution CLI

## Goal
Expose the existing generated-tool evolution lifecycle through the CLI so tool candidates can be inspected, reviewed, installed, and disabled without going through a model run.

## Requirements
- Keep `mnemo tools --state-dir ...` as the existing list-tools behavior.
- Add explicit tool lifecycle commands for candidate listing, candidate review, candidate install, and generated tool uninstall.
- Reuse `ToolEvolutionService` and `ToolRegistry.from_store`; do not duplicate validation logic in the CLI.
- Keep outputs compact and JSON-capable.
- Normalize expected missing candidate/tool errors through the existing `mnemo:` CLI error boundary without tracebacks.

## Acceptance Criteria
- [x] `mnemo tools candidates --state-dir ... --json` lists stored tool candidates.
- [x] `mnemo tools review <candidate_id> --state-dir ... --json` updates and returns review status.
- [x] `mnemo tools install <candidate_id> --state-dir ... --json` installs a ready alias candidate as an active generated tool.
- [x] `mnemo tools uninstall <name> --state-dir ... --json` disables an active generated tool.
- [x] Existing `mnemo tools --state-dir ... --json` continues to list active built-in and generated tool specs.
- [x] Missing candidate/tool CLI paths exit non-zero with `mnemo:` stderr and no Python traceback.
- [x] Backend contracts and implementation checklist reflect the shipped CLI surface.

## Technical Notes
- This is a CLI surface over existing backend services, not a new workflow router.
- The install command should validate against currently available registered tools by using `ToolRegistry.from_store(store)`.
- Tests should use stdlib `unittest` patterns already present in `tests/test_cli.py`.
