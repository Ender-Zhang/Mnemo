# Expose Eval Case CLI

## Goal
Expose stored eval cases through a lightweight CLI so humans and scripts can inspect and record eval outcomes used by memory, skill, and tool evolution gates.

## Requirements
- Add a top-level `mnemo evals` command with list and record operations.
- Reuse existing `StateStore` eval case APIs; do not introduce a new workflow engine.
- Support status, tool target, skill target, and limit filters for listing.
- Support recording pass/fail results with an optional JSON object payload.
- Normalize missing eval case and invalid JSON input errors through the existing `mnemo:` CLI error boundary.
- Keep output compact and JSON-capable.

## Acceptance Criteria
- [x] `mnemo evals list --state-dir ... --json` lists stored eval cases.
- [x] `mnemo evals list --tool-name ...` and `--skill-name ...` use existing target filters.
- [x] `mnemo evals record <case_id> passed --result-json '{"ok":true}' --state-dir ... --json` persists status and result.
- [x] Missing eval case and invalid `--result-json` exit non-zero with `mnemo:` stderr and no Python traceback.
- [x] README, backend contracts, and implementation checklist reflect the shipped CLI surface.

## Technical Notes
- The command is a thin operational surface for existing model-driven eval tools.
- Status choices remain `passed` and `failed`, matching `eval_record_result`.
