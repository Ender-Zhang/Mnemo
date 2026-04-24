# Implement Tool Boundary Cards

## Goal

Add a lightweight tool boundary that keeps model-native tool calls as the decision surface while Mnemo owns execution safety, result summaries, and UI evidence cards.

## Scope

- Add a compact tool execution policy for `read`, `write`, `external`, and `admin`.
- Keep default policy permissive for built-in read/write tools so the local runtime remains usable.
- Persist full tool results, but expose compact summaries to model turns and chat events.
- Add evidence cards for UI inspection without forcing a workflow.
- Cover allowed and denied tool calls with unit tests.

## Non-Goals

- No shell, file, browser, or external tool implementation in this task.
- No human approval workflow.
- No generated tool lifecycle.
- No daemon or web server changes.
