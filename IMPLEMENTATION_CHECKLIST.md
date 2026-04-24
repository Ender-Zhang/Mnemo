# Mnemo Implementation Checklist

This file tracks implementation status against the design package. Keep it updated whenever a Trellis task lands.

## Legend

- `[x]` implemented and covered by at least smoke tests
- `[~]` partially implemented or scaffolded
- `[ ]` not implemented yet

## Foundation

- [x] Trellis project workflow initialized.
- [x] Python package moved to root `mnemo/` package layout.
- [x] Layered package structure: `core`, `storage`, `runtime`, `tools`, `providers`, `interfaces`.
- [x] CLI entrypoint via `python -m mnemo` and `mnemo` console script.
- [x] Local deterministic runtime for offline tests and harness development.
- [x] SQLite state directory with conversations, missions, runs, events, tools, candidates, artifacts.
- [x] RunLedger append/read facade.
- [x] Unit smoke tests for storage, runtime, CLI, provider placeholders.

## Runtime And Streaming

- [x] Conversation and Mission creation/reuse for multi-turn continuity.
- [x] Run lifecycle events persisted to RunLedger.
- [x] `ChatEvent` model for UI/CLI streaming.
- [x] CLI `--stream` NDJSON output.
- [x] Tool/action projection events: `action.queued`, `action.started`, `action.completed`.
- [x] Learning chip projection for memory candidates.
- [x] Artifact card projection for artifact updates.
- [~] Provider adapter interface exists.
- [ ] OpenAI-compatible provider-backed runtime.
- [ ] Provider-native tool calls bridged into ToolHarness.
- [ ] True streaming provider delta support.
- [ ] Timeout/retry/cancellation policy.
- [ ] Daemon, queue, single-instance lock, crash recovery.
- [ ] Replay harness.

## Tools

- [x] Provider-safe `ToolCallEnvelope`.
- [x] ToolRegistry and ToolHarness.
- [x] Core tool specs: `memory_search`, `memory_read`, `working_note`, `skills_list`, `skill_view`, `artifact_update`, `ask_user`.
- [x] Learning tool specs: `memory_write_candidate`, `skill_propose_candidate`, `tool_propose_candidate`, `eval_propose_case`, `learning_discard`.
- [x] Tool calls and results persisted.
- [ ] External tools: web/search/browser, shell, file read/write/patch, app connectors.
- [ ] Lightweight permission gate for read/write/external/admin.
- [ ] Tool result compression and evidence cards.
- [ ] Generated tool lifecycle and evaluation gate.

## Memory

- [x] Memory candidate writes with evidence/provenance.
- [x] Memory candidate search/read.
- [x] Stable memory is not directly mutated by normal task tools.
- [ ] Memory engine pages/indexes beyond candidates.
- [ ] Associative recall / LLM Wiki style memory graph.
- [ ] Conflict detection and confidence updates.
- [ ] W0 working memory to long-term candidate pipeline.
- [ ] DreamCycle idle memory consolidation.
- [ ] Daily compiled L1 cache-friendly memory snapshot.
- [ ] Memory eval cases and regression gates.

## Skills And Evolution

- [x] Skill draft storage and list/view tools.
- [~] Skill proposal tool exists, but no filesystem `SKILL.md` lifecycle yet.
- [ ] Cross-client skill scanner for `.agents/skills`, `.mnemo/skills`, Claude/Hermes/OpenClaw paths.
- [ ] Progressive skill index/summary/full load.
- [ ] Skill usage tracking and outcome scoring.
- [ ] Skill patch/proposal review lifecycle.
- [ ] SOP crystallization from successful runs.
- [ ] Skill eval harness.

## Prompt And Context

- [~] Runtime records a minimal `prompt.assembled` event.
- [ ] PromptBlock model.
- [ ] PromptAssembler with stable prefix and dynamic tail.
- [ ] Tool card/schema budget separation.
- [ ] Skill and memory progressive disclosure.
- [ ] KV-cache-first prompt assembly ordering.
- [ ] Prompt inspection command.
- [ ] Context compression.

## Frontend Experience

- [x] Backend `ChatEvent` stream contract started.
- [x] Action and learning events are representable in stream.
- [ ] User-facing single-chat web frontend.
- [ ] Universal composer.
- [ ] Inline action cards.
- [ ] Inline artifact cards and artifact viewer.
- [ ] Inline decision cards.
- [ ] Event replay/resume with `sinceEventId`.
- [ ] Streaming transport API.

## Provider And Model Integration

- [~] Provider adapter boundary exists.
- [ ] OpenAI-compatible chat completions adapter.
- [ ] Anthropic adapter.
- [ ] Provider config from environment/CLI without persisting secrets.
- [ ] Model/tool loop with provider-native tool call schema.
- [ ] Streaming response parser.
- [ ] Provider error normalization.
- [ ] Local endpoint smoke command using user-provided credentials.

## Evaluation And Harness

- [x] Basic unit tests.
- [ ] Golden personalization cases.
- [ ] Runtime smoke replay tests.
- [ ] Memory safety tests.
- [ ] Skill evolution tests.
- [ ] Provider fake server tests.
- [ ] CLI and package install tests in CI.

## Persistence And Operations

- [x] SQLite schema creation.
- [x] State dirs for wiki, skills, runs, artifacts.
- [ ] Schema migrations.
- [ ] JSONL trace mirror.
- [ ] Event outbox.
- [ ] Config file and env override model.
- [ ] Daemon status command.
- [ ] Backup/export/import.

## Current Trellis Focus

- [~] `04-24-implement-provider-backed-runtime`: implement OpenAI-compatible provider config, adapter, streaming bridge, timeout handling, and fake-server tests.
