# Expose Eval Case Creation CLI

## Goal
Complete the lightweight eval CLI surface by allowing humans and scripts to create stored eval cases that can later be recorded and used by skill/tool review gates.

## Requirements
- Add `mnemo evals create <run_id> <name> --case-json OBJECT`.
- Reuse `StateStore.add_eval_case`; do not introduce a new eval workflow engine.
- Validate that the source run exists before creating the case.
- Parse `--case-json` as a JSON object using the existing CLI JSON-object parser.
- Keep output compact and JSON-capable.
- Normalize missing run and invalid JSON errors through the existing `mnemo:` CLI error boundary.

## Acceptance Criteria
- [x] `mnemo evals create <run_id> <name> --case-json '{"tool_candidate":"x"}' --json` persists a draft eval case.
- [x] Created cases are visible through `mnemo evals list` and can be updated through `mnemo evals record`.
- [x] Missing run and invalid `--case-json` exit non-zero with `mnemo:` stderr and no Python traceback.
- [x] README, backend contracts, and implementation checklist reflect the shipped CLI surface.

## Technical Notes
- This command exposes the same primitive as `eval_propose_case` for non-model/manual harness use.
- The model-driven path remains provider-native tool calling; this CLI is an operational surface.
