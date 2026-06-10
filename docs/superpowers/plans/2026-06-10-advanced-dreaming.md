# Advanced Dreaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add semi-automatic advanced Dreaming with persistent reorganization proposals and a WebUI switch.

**Architecture:** Extend existing Dreaming rather than replacing it. Existing low-risk actions continue through `apply_dream_actions`; advanced high-risk actions are converted into persisted proposals in SQLite and exposed through SDK/HTTP/WebUI.

**Tech Stack:** Python stdlib, SQLite, React + TypeScript + Vite, existing Mnemo Memory SDK/API.

---

## Task 1: Proposal Storage

- [x] Add `dream_proposals` table in `mnemo_memory/storage/sqlite.py`.
- [x] Add store methods to create/list/get/update proposals.
- [x] Add row normalization helper.

## Task 2: Dream Engine

- [x] Add advanced Dream tool names and high-risk classification.
- [x] Extend `build_dream_plan(..., advanced_dreaming=False)`.
- [x] Extend `dream_maintenance(..., advanced_dreaming=False, execution_policy="semi_auto")`.
- [x] Auto-apply `memory_link_pages`.
- [x] Persist high-risk actions as pending proposals.
- [x] Add methods to list/apply/reject proposals.

## Task 3: SDK and HTTP API

- [x] Extend `MemoryClient.dream_run`.
- [x] Add `dream_proposals`, `apply_dream_proposal`, and `reject_dream_proposal`.
- [x] Update `dispatch_memory_api`.
- [x] Update `memory_api_schema`.
- [x] Pass advanced parameters through `run_dream_with_lock`.

## Task 4: Provider Prompt

- [x] Teach `OpenAICompatibleMemoryMaintainer` to accept advanced plans.
- [x] Add advanced tool descriptions to the system prompt when the plan allows them.

## Task 5: WebUI

- [x] Add `advancedDreaming` localStorage state.
- [x] Include advanced Dreaming in `dream-run` payload.
- [x] Fetch proposals during refresh.
- [x] Add Settings switch.
- [x] Add Maintenance proposal panel with apply/reject controls.
- [x] Update success message with proposal counts.

## Task 6: Tests and Build

- [x] Add backend tests for proposal creation/list/apply/reject.
- [x] Add WebUI source-level tests for switch and payload.
- [x] Run `python3 -m unittest discover -s tests -v`.
- [x] Run `npm --prefix webui run build`.
- [x] Rebuild static WebUI assets.
