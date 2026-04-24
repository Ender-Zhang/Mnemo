# Implement Skill Usage Scoring

## Goal
Add a lightweight skill usage and outcome signal layer so skills can self-evolve from observed use without introducing a fixed workflow.

## Requirements
- Record when the model loads a full skill body via `skill_view`.
- Expose a provider-native tool for the model to record skill outcomes after a task.
- Store usage/outcome events with evidence, score, and run provenance.
- Include compact usage stats in skill context cards.
- Keep the mechanism model-driven: no router, no mandatory workflow.
- Cover storage, tool, and service card behavior with tests.

## Acceptance Criteria
- [x] `skill_view` records a `viewed` usage event.
- [x] `skill_record_outcome` records success/failure/neutral outcomes with bounded score.
- [x] Skill cards include compact usage stats and omit full bodies.
- [x] Skill cards are sorted deterministically using usage stats.
- [x] Tool result summaries/evidence stay compact.
- [x] Unit tests cover storage, tool usage, and card projection.
