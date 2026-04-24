# Implement Single Chat Web Frontend

## Goal

Provide a lightweight user-facing web experience where the user only sees one chat surface, with streamed assistant output and inline action/artifact/learning cards backed by Mnemo `ChatEvent`.

## Scope

- Add a stdlib HTTP server command.
- Serve a single-page chat UI with a bottom composer.
- Stream `ChatEvent` NDJSON from `/api/chat`.
- Preserve multi-turn continuity through conversation and mission ids.
- Render assistant deltas, actions, artifacts, sources, learning chips, and errors inline.
- Add backend HTTP smoke tests.

## Non-Goals

- No operational dashboard.
- No auth/user account system.
- No framework build chain.
- No browser-side provider secret storage.
