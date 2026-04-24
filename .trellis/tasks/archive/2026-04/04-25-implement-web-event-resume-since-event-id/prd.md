# Implement Web Event Resume SinceEventId

## Goal

Make the single-chat web frontend recover chat stream events by durable `ChatEvent.event_id`, so reloads and reconnects can resume without depending on internal ledger sequence numbers.

## Scope

- Keep the existing `/api/events?since=` sequence API.
- Add `/api/events?run_id=<id>&chat=1&sinceEventId=<event_id>`.
- Return chat events after the matching event id.
- Return all chat events if `sinceEventId` is unknown, so clients can safely rehydrate.
- Persist the latest event id in the browser.
- De-duplicate replayed and streamed events in the browser.
- Rehydrate the last run on page load.
- Update tests, specs, and checklist.

## Acceptance

- [x] Backend replay supports `sinceEventId` and preserves existing `since`.
- [x] Unknown `sinceEventId` returns all chat events for the run.
- [x] Web client stores `mnemo.last_event_id`.
- [x] Web client avoids duplicate event rendering.
- [x] Web client can replay the last run on load.
- [x] Existing web chat and replay tests still pass.
- [x] Full unit suite passes.
- [x] Changes are committed locally.
