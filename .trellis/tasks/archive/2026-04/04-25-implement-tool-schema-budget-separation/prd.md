# Implement Tool Schema Budget Separation

## Goal

Make prompt budgeting explicitly separate human-readable tool cards from provider-native tool schemas so optional prompt context can be dropped without implying that tools are unavailable to the model.

## Scope

- Track prompt token estimates separately from provider tool schema estimates.
- Record compact tool schema metadata in `prompt.assembled` metadata without raw schema payloads.
- Keep provider-native tool schemas outside prompt block budgeting.
- Ensure dropping `tools.cards` under a tight prompt budget does not remove tool schema metadata.
- Preserve deterministic tool ordering.
- Cover behavior with prompt/runtime tests.
- Update prompt spec and implementation checklist.

## Acceptance

- [x] Prompt metadata includes prompt-only token estimate and separate tool schema token estimate.
- [x] Tool schema metadata includes count and ordered names but not raw schema content.
- [x] Tight prompt budgets may drop `tools.cards` while retaining tool schema metadata.
- [x] Existing provider-native tool availability path remains unchanged.
- [x] Focused and full unit suites pass.
- [x] Changes are committed locally.
