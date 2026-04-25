# Approved tool approval execution

## Goal
Close the first high-risk action loop: when a user accepts a persisted `tool_approval` Decision Card, Mnemo replays the exact stored tool call through ToolHarness and returns compact execution evidence.

## Requirements
- Execute only accepted, newly resolved `tool_approval` Inbox items.
- Reuse `ToolHarness`, `ToolRegistry`, `ToolExecutionPolicy`, RunLedger, and compact tool results.
- Execute the stored provider-native tool call against the original source run and mission.
- Return compact `tool_result` metadata from Web and CLI resolve paths.
- Append auditable approval execution events to the source run ledger.
- Do not implement standing authority or automatic repeated approvals.
- Do not execute rejected, ignored, malformed, missing-source, or already-resolved approval items.

## Acceptance
- [x] Accepted `tool_approval` decisions execute the stored tool call once.
- [x] Rejected/ignored decisions do not execute tools.
- [x] Repeated resolution does not re-execute.
- [x] Web and CLI return compact execution metadata.
- [x] Existing decision resolution behavior remains compatible.
- [x] Specs and checklist describe the implemented foundation and remaining limits.
