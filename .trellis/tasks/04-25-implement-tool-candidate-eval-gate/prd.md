# Implement Tool Candidate Eval Gate

## Goal
Add a lightweight lifecycle gate for generated tool candidates so tool self-evolution can move from draft proposals toward reviewable, eval-backed candidates.

## Requirements
- Preserve the provider-native loop: the model proposes tools and can request review through tools.
- Add storage APIs to read/list/update tool candidates and eval cases.
- Add an eval result API for marking proposed eval cases as passed or failed.
- Add a small tool evolution service that validates candidate spec shape and requires at least one passed linked eval case.
- Add model-callable tools for recording eval results and reviewing a tool candidate.
- Keep generated tools inactive; this task only gates candidates to `ready` or `blocked:*`.

## Acceptance Criteria
- [x] Tool candidates can be listed/read and status-updated.
- [x] Eval cases can be listed/read and status-updated.
- [x] Candidate review blocks invalid specs.
- [x] Candidate review blocks candidates without passed linked evals.
- [x] Candidate review marks valid candidates with passed linked evals as `ready`.
- [x] Tool result summaries/evidence stay compact.
- [x] Unit tests cover storage, service, and model-facing tools.
