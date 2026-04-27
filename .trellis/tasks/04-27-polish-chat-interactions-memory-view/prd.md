# Polish Chat Interactions And Memory View

## Goal
Make the single-chat frontend feel responsive and less repetitive: Enter sends, pending assistant feedback appears immediately, tool calls show useful details/results in one place, recall avoids duplicate text, and users can inspect ten-dimension memory coverage.

## Requirements
- Enter sends the composer message; Shift+Enter inserts a newline.
- After sending, show a visible assistant pending indicator until the first assistant delta/final/error arrives.
- Tool action cards should show compact call content and completed result, without duplicating the same evidence as separate source cards.
- Recall cards should avoid repeating identical title/summary text.
- Add a lightweight ten-dimension memory view from the settings drawer and a backend endpoint with compact counts/summaries.
- Preserve single composer, replay, stop, settings, artifact, decision, learning, and recall behavior.

## Acceptance Criteria
- [x] Web asset tests cover Enter send and Shift+Enter newline handling.
- [x] Web asset tests cover pending assistant indicator and cleanup.
- [x] Web asset tests cover compact tool details/result rendering and duplicate source suppression.
- [x] Web API test covers `/api/memory/ontology` without leaking raw bodies/secrets.
- [x] Web asset tests cover ten-dimension memory view loading from settings.
- [x] Full tests and package smoke pass.
