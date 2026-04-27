# Polish Reference Frontend Markdown

## Goal
Bring the web UI much closer to the generated product reference: a high-end single-chat workspace with visible user history/context, non-duplicated action display, refined cards, and Markdown-rendered assistant output.

## Requirements
- Render assistant Markdown safely without using `innerHTML` for model output.
- Preserve streaming behavior while allowing the final assistant message to format Markdown.
- Replay user history from `turn.started` events so refreshed sessions show prior user asks.
- Add a compact user/context panel that surfaces conversation, mission, last run, and recent user intent.
- De-duplicate activity/action display so queued/started/completed updates merge into one activity row per action.
- Restyle the UI to more closely match the generated reference: left labeled rail, spacious centered conversation, elegant right activity/context panel, high-quality cards, composer, and mobile behavior.
- Keep existing artifact, recall, learning, decision, settings, cancellation, and resume behavior.

## Acceptance Criteria
- [x] Assistant messages render common Markdown: headings, paragraphs, bullets, ordered lists, code blocks, inline code, bold, italic, and links.
- [x] Markdown rendering is DOM-built and escapes untrusted text.
- [x] Live streaming remains text-first and final/replayed assistant messages render Markdown.
- [x] Replayed last run shows the historical user prompt from `turn.started` instead of only assistant/cards.
- [x] Activity panel merges action lifecycle updates rather than creating repeated duplicate rows.
- [x] Right panel shows compact user/context state from local continuity ids and recent user intent.
- [x] Asset tests cover Markdown rendering, history replay, action de-duplication, and reference shell vocabulary.
- [x] Full tests and package smoke pass.

## Technical Notes
- No frontend bundler, framework, or external markdown dependency.
- No backend API changes unless existing event payloads prove insufficient.
