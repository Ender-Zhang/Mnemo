# Implement Memory Conflict And Reinforcement Signals

## Goal
Improve the memory engine so dream consolidation can detect duplicate reinforcement and obvious conflicts without directly overwriting stable memory.

## Requirements
- Preserve the existing candidate-first memory model.
- Reinforce an existing stable memory page when a duplicate candidate arrives.
- Detect obvious contradictory candidates against active memory pages and route them to review.
- Use memory links for provenance (`reinforces`, `conflicts_with`) instead of hidden side effects.
- Keep the mechanism lightweight and deterministic for harness tests; future model decisions can consume these signals.
- Cover duplicate reinforcement and conflict routing with unit tests.

## Acceptance Criteria
- [x] Duplicate candidates update existing page confidence upward and are rejected as duplicates.
- [x] Duplicate candidates link to the reinforced page.
- [x] Conflicting candidates are not promoted automatically.
- [x] Conflicting candidates link to the conflicting page and receive a review status.
- [x] Dream consolidation returns conflict entries for harness inspection.
