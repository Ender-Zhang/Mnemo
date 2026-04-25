# Mnemo Implementation Checklist

This file tracks implementation status against the design package. Keep it updated whenever a Trellis task lands.

## Legend

- `[x]` implemented and covered by at least smoke tests
- `[~]` partially implemented or scaffolded
- `[ ]` not implemented yet

## Current Alignment Snapshot

- [x] Runnable core: CLI/Web/local/provider runtime, RunLedger, basic memory/skill/tool loops, streaming events, package smoke, and core eval suites work.
- [~] Product completeness: several systems exist as foundations but do not yet satisfy the full design package contracts.
- [ ] Extensions: Watch/Sense/Sub-Agent/RuntimeAdapter/MCP/SDK and richer external integrations remain future Trellis work unless explicitly prioritized.

## Foundation

- [x] Trellis project workflow initialized.
- [x] Python package moved to root `mnemo/` package layout.
- [x] Layered package structure: `core`, `storage`, `runtime`, `tools`, `providers`, `interfaces`.
- [x] CLI entrypoint via `python -m mnemo` and `mnemo` console script.
- [x] Local deterministic runtime for offline tests and harness development.
- [x] SQLite state directory with conversations, missions, runs, events, tools, candidates, artifacts.
- [x] RunLedger append/read facade.
- [x] Unit smoke tests for storage, runtime, CLI, and provider adapters.

## Runtime And Streaming

- [x] Conversation and Mission creation/reuse for multi-turn continuity.
- [x] Run lifecycle events persisted to RunLedger.
- [x] `ChatEvent` model for UI/CLI streaming.
- [x] CLI `--stream` NDJSON output.
- [x] Tool/action projection events: `action.queued`, `action.started`, `action.completed`.
- [x] Learning chip projection for memory candidates.
- [x] Artifact card projection for artifact updates.
- [x] Provider adapter interface exists.
- [x] OpenAI-compatible provider-backed runtime.
- [x] Provider-native tool calls bridged into ToolHarness.
- [x] True streaming provider delta support.
- [x] Timeout/retry/cancellation policy: provider timeout, non-streaming retry, and cooperative persisted cancellation exist.
- [~] Daemon, queue, single-instance lock, and stale queue recovery exist; full Supervisor priority classes, Inbox recovery, Watch recovery, child runtime cleanup, and W0 pending recovery are not implemented.
- [~] Replay harness exists as trace summary and smoke/eval support; full deterministic/live-tools/dry-run replay diff modes are not implemented.

## Tools

- [x] Provider-safe `ToolCallEnvelope`.
- [x] ToolRegistry and ToolHarness.
- [x] Core tool specs: `memory_search`, `memory_read`, `working_note`, `skills_list`, `skill_view`, `artifact_update`, `ask_user`.
- [x] Learning tool specs: `memory_write_candidate`, `skill_propose_candidate`, `tool_propose_candidate`, `eval_propose_case`, `learning_discard`.
- [x] Tool calls and results persisted.
- [x] External tools: workspace file search/read/write/patch, HTTP fetch, shell execution, and lightweight browser/app connectors exist.
- [~] Lightweight permission gate for read/write/external/admin exists; side-effect flags, Decision Card escalation, standing authority, and sandbox profile enforcement are not complete.
- [x] Tool result compression and evidence cards.
- [~] Generated tool lifecycle and evaluation gate: draft candidates, eval result recording, readiness gate, and safe alias installation exist; shadow dry-run, rollback, extension packaging, and richer eval gates are not complete.

## Memory

- [x] Memory candidate writes with evidence/provenance.
- [x] Memory candidate search/read.
- [x] Stable memory is not directly mutated by normal task tools.
- [x] Memory engine pages/indexes beyond candidates.
- [x] Associative recall / LLM Wiki style memory graph.
- [~] Conflict detection and confidence updates exist for simple duplicate/conflict cases; tombstone, decay, stale review, and selective forgetting are not implemented.
- [x] W0 working memory to long-term candidate pipeline.
- [~] DreamCycle idle memory consolidation exists as deterministic candidate promotion and L1 snapshot compilation; it is not yet model-led, scheduled by idle windows, or delta-only across all memory maintenance tasks.
- [~] L1 cache-friendly memory snapshot compile/load exists; daily scheduling and Dream-managed cache invalidation are not complete.
- [~] Memory eval cases and regression gates cover smoke/safety cases plus L4 session-search regressions; full wrong-memory, over-personalization, Memory Health, and injection-scan gates are not complete.
- [x] L4 cross-session FTS5 search over run user/assistant messages with LIKE fallback and bounded snippets.
- [ ] Memory QueryPlanner with lexical/semantic/temporal/dimension planning, RRF/MMR fusion, and tombstone/stale annotations.
- [ ] Memory tombstones, decay passes, selective forgetting, memory health reports, and low-friction memory cultivation cards.
- [ ] Memory write taint tracking and prompt-injection scanner across user, web, file, tool result, imported skill, MCP, and external runtime sources.

## Skills And Evolution

- [x] Skill draft storage and list/view tools.
- [x] Skill proposal tool exists with generated `SKILL.md` promotion.
- [x] Cross-client skill scanner for `.agents/skills`, `.mnemo/skills`, Claude/Hermes/OpenClaw paths.
- [x] Progressive skill index/summary/full load.
- [x] Skill usage tracking and outcome scoring.
- [~] Skill patch/proposal review lifecycle: proposal, exact patch candidate, eval, review, and promotion gates exist; import/export/update/enable/disable/rollback/doctor/why operations and external shadow-copy lifecycle are not complete.
- [~] SOP crystallization from successful runs exists; automatic after-turn learning packets and model-selected 0..N mixed candidate generation are not a standard runtime phase yet.
- [~] Skill eval harness exists for built-in cases; full red-team, selection precision, rollback-rate, and cross-client compatibility suites are not complete.

## Prompt And Context

- [x] Runtime records `prompt.assembled` metadata.
- [x] PromptBlock model.
- [x] PromptAssembler with stable prefix and dynamic tail.
- [x] Tool card/schema budget separation.
- [x] Skill and memory progressive disclosure.
- [x] KV-cache-first prompt assembly ordering.
- [x] Prompt inspection command.
- [~] Context compression exists at a basic budget/drop level; full pre-run safety compression, in-loop compaction, mission checkpoint compression, and provider cache-control integration are not complete.
- [~] Soul.md loading and bounded prompt injection are implemented; user-confirmed Soul evolution and explicit cache invalidation are not complete.
- [~] Workspace bootstrap blocks for `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, `BOOTSTRAP.md`, `MEMORY.md`, `CLAUDE.md`, and cursor rules load with caps, truncation markers, and warning metadata; prompt modes/provider cache controls are not complete.
- [ ] Prompt modes beyond recorded `full`: `minimal`, `capsule`, and `none` with enforced disclosure boundaries.
- [ ] Stable ToolBundle epochs and lazy schema expansion for large MCP/external tool surfaces.

## Frontend Experience

- [x] Backend `ChatEvent` stream contract started.
- [x] Action and learning events are representable in stream.
- [x] User-facing single-chat web frontend.
- [~] Universal composer exists for text; voice, files, screenshots, links, app mention, and selected artifact/span context are not complete.
- [x] Busy-state stop/cancel control in the single composer.
- [x] Stop control targets the current active run rather than replay state.
- [x] New/reset is guarded while a run is streaming.
- [x] Inline action cards.
- [x] Inline artifact cards and artifact viewer.
- [~] Inline decision cards can render; card actions, response API, persistence, standing authority, and high-risk approval flow are not implemented.
- [x] Event replay/resume with `sinceEventId`.
- [x] Streaming transport API.
- [ ] Recall in chat for past work, artifacts, decisions, and knowledge with actionable result cards.
- [ ] Learning chips with user actions such as "以后这样", "这次而已", undo, and high-risk confirmation.
- [ ] Minimal settings drawer for connected apps, permissions, quiet hours, learned preferences, and data controls.
- [ ] Artifact operations beyond open/view: continue edit, export, compare versions, apply/revert diff, and send draft.

## Provider And Model Integration

- [x] Provider adapter boundary exists.
- [x] OpenAI-compatible chat completions adapter.
- [x] Anthropic adapter.
- [x] Provider config from environment/CLI without persisting secrets.
- [x] Model/tool loop with provider-native OpenAI/Anthropic tool call schema.
- [x] Streaming response parser.
- [x] Provider error normalization.
- [x] Local endpoint smoke command using user-provided credentials.
- [ ] Generic provider capability registry for prompt cache controls, tool bundle epochs, model context limits, and provider-specific fallback modes.

## Evaluation And Harness

- [x] Basic unit tests.
- [x] Golden personalization cases.
- [x] Runtime smoke replay tests.
- [x] Memory safety tests.
- [x] Skill evolution tests.
- [x] Provider fake server tests.
- [x] Standard tool edge regression tests for binary file reads and shell timeouts.
- [x] CLI and package install tests in CI.
- [~] Harness gates exist as built-in smoke suites; variant comparison (`no_memory`, `skills_only`, `full_mnemo`), quantitative thresholds, external-harness suite, proactive-watch suite, and release gate reports are not complete.

## Persistence And Operations

- [x] SQLite schema creation.
- [x] State dirs for wiki, skills, runs, artifacts.
- [x] Schema migrations.
- [x] JSONL trace mirror.
- [x] Event outbox.
- [x] Config file and env override model.
- [x] Daemon status command.
- [x] Backup/export/import.
- [ ] Core SDK / OpenAPI or IDL contract for language-neutral integrations.
- [ ] MCP server exposing context/update/recall/search/watch/skills/tools/cron/run/replay/eval/status tools.
- [ ] Minimal Inbox/Decision persistence tables and CLI/API inspection.
- [ ] Watch/Cron persistence and scheduled event processing.
- [x] Sessions/messages/L4 search tables and FTS5 indexes for persisted run messages.

## Remaining Trellis Focus

- [x] README reflects current runtime, provider, web, daemon, cancellation, evolution, and harness workflows.
- [~] Implementation checklist now separates runnable foundations from incomplete full-design capabilities.
- [~] Highest-priority core alignment: L4 memory search and Soul/bootstrap prompt input foundations are implemented; unified after-turn learning packet, interactive Decision/Inbox loop, and frontend recall/learning actions remain.
- [ ] Highest-priority integration alignment: SDK/MCP server and external RuntimeAdapter with context capsule boundaries.
- [ ] Extension alignment: Watch/Proactive, Sense/Android, Sub-Agent/AgentCard, richer generated-tool extension packaging, messaging/calendar/mail connectors, and full harness suites.

## Recently Landed Trellis Tasks

- [x] `04-25-04-25-refresh-readme-current-capabilities`: README and public runtime wording now describe the current single-chat runtime, provider setup, web UI, daemon, cancellation, memory/skill/tool operations, backup, and validation workflows.
- [x] `04-25-04-25-tighten-web-fetch-url-validation`: `web_fetch` now rejects malformed HTTP/HTTPS URLs before network I/O and has standard tool regression coverage.
- [x] `04-25-04-25-cover-prompt-required-budget-overflow`: prompt budgeting now has regression coverage for impossible budgets that drop optional blocks while preserving required blocks and reporting `budget_exceeded=true`.
- [x] `04-25-04-25-cover-tool-evolution-missing-candidate`: tool evolution missing-candidate paths now have service-level `NotFoundError` coverage and model-facing compact failed `ToolResult` coverage.
- [x] `04-25-04-25-guard-web-event-shape`: web chat event handling now ignores non-object stream/replay payloads before state persistence or rendering, with asset regression coverage.
- [x] `04-25-04-25-normalize-cli-memory-candidate-errors`: CLI memory promote/reject now normalize missing candidate errors as `mnemo:` stderr without Python tracebacks.
- [x] `04-25-04-25-normalize-cli-skill-service-errors`: CLI skill promote/eval/crystallize now normalize expected service errors as `mnemo:` stderr without Python tracebacks.
- [x] `04-25-04-25-expose-tool-evolution-cli`: CLI now exposes tool candidate listing, review, install, and generated-tool uninstall through the existing ToolEvolutionService lifecycle.
- [x] `04-25-04-25-expose-eval-case-cli`: shared CLI eval case listing and pass/fail result recording now support memory/skill/tool evolution gates without requiring direct storage access.
- [x] `04-25-04-25-expose-eval-case-create-cli`: shared CLI eval case creation now lets manual harnesses add draft skill/tool eval cases from existing runs before recording results.
- [x] `04-25-04-25-expose-skill-usage-cli`: CLI now exposes stored skill usage/outcome events and aggregate stats without mutating skill state.
- [x] `04-25-04-25-validate-openai-compatible-provider-chain`: OpenAI-compatible `config smoke --stream` now validates streaming-only chat models, and the supplied `gpt-5.4` endpoint was exercised through streaming smoke, run, prompt inspect, events, and replay.
- [x] `04-25-expose-memory-read-cli`: CLI now reads memory candidates and stable pages by id with normalized missing-id errors.
- [x] `04-25-expose-memory-list-cli`: CLI now lists draft candidates, active pages, or unfiltered memory inventory without mutating memory state.
- [x] `04-25-expose-memory-links-cli`: CLI now inspects outgoing and incoming associative memory graph links without mutating memory state.
- [x] `04-25-expose-memory-snapshot-cli`: CLI now inspects the existing compact L1 memory snapshot used by prompt assembly without regenerating it.
- [x] `04-25-expose-memory-notes-cli`: CLI now inspects W0 working notes and DreamCycle input/output statuses without mutating note state.
- [x] `04-25-expose-artifacts-cli`: CLI now lists and reads stored mission artifacts while keeping list/event payloads free of body text.
- [x] `04-25-expose-runs-inspection-cli`: CLI now lists compact run history and shows full run records by id before users open events, replay, prompts, or artifacts.
- [x] `04-25-expose-continuity-inspection-cli`: CLI now lists and reads conversation/mission continuity ids, with mission checkpoints only returned by explicit mission reads.
- [x] `04-25-normalize-missing-run-trace-cli-errors`: CLI trace commands now fail clearly for missing runs instead of returning empty events or empty replay summaries.
- [x] `04-25-04-25-implement-provider-retry-policy`: provider config supports opt-in non-streaming retries for transient timeout/connection/retryable-status failures while keeping streaming single-attempt.
- [x] `04-25-04-25-implement-run-cancellation-foundation`: runs and queued daemon jobs can be cancelled durably, and provider/local runtimes complete observed cancellations with `status="cancelled"`.
- [x] `04-25-04-25-implement-browser-app-connectors`: lightweight `browser_open` and `app_open` connector tools are provider-native, policy-gated, dry-run testable, and compact in results.
- [x] `04-25-04-25-implement-web-run-cancellation`: web chat uses a threaded server, `/api/runs/cancel`, and composer stop control for cooperative run cancellation.
- [x] `04-25-04-25-add-standard-tool-edge-coverage`: standard tool harness now has explicit binary file read and shell timeout regression coverage.
- [x] `04-25-04-25-fix-web-stop-active-run-target`: web Stop now uses volatile `activeRunId` so a fresh turn cannot cancel the previous replay run.
- [x] `04-25-04-25-guard-web-reset-during-active-run`: web New/reset is disabled and guarded during active streams to preserve single-chat continuity.
- [x] `04-25-04-25-implement-skill-patch-candidates`: model-directed `skill_patch_candidate` creates draft skill revisions with exact replacement checks, compact evidence, and unchanged source skills.
- [x] `04-25-implement-file-patch-tool`: admin-gated `file_patch` applies exact workspace-scoped UTF-8 replacements with ambiguity and traversal protection.
- [x] `04-25-implement-tool-schema-budget-separation`: prompt metadata separates prompt token estimates from provider-native tool schema estimates without storing raw schemas.
- [x] `04-25-implement-prompt-bootstrap-foundation`: runtime, provider, CLI, and Web now inject bounded `SOUL.md` and workspace bootstrap context into cache-aware prompt assembly while keeping prompt metadata content-free.
- [x] `04-25-implement-associative-memory-recall`: memory search surfaces one-hop linked active pages through direct and reverse wiki links, and `memory_read` loads stable pages.
- [x] `04-25-implement-cross-client-skill-roots`: default skill roots include workspace/home Claude, Hermes, and OpenClaw skill directories with deterministic de-duplication.
- [x] `04-25-implement-artifact-viewer`: web artifact cards fetch stored artifact bodies on demand through `/api/artifacts` while stream events stay compact.
