# Mnemo Implementation Checklist

This file tracks implementation status against the design package. Keep it updated whenever a Trellis task lands.

## Legend

- `[x]` implemented and covered by at least smoke tests
- `[~]` partially implemented or scaffolded
- `[ ]` not implemented yet

## Current Alignment Snapshot

- [x] Runnable core: CLI/Web/local/provider runtime, RunLedger, basic memory/skill/tool loops, streaming events, package smoke, and core eval suites work.
- [~] Product completeness: several systems exist as foundations but do not yet satisfy the full design package contracts.
- [ ] Extensions: Watch/Sense/Sub-Agent/RuntimeAdapter and richer external integrations remain future Trellis work unless explicitly prioritized.

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
- [~] Daemon, queue, single-instance lock, stale queue recovery, and scheduled watch/cron enqueue foundation exist; full Supervisor priority classes, Inbox recovery, Watch recovery, child runtime cleanup, and W0 pending recovery are not implemented.
- [~] Replay harness exists as trace summary and smoke/eval support; full deterministic/live-tools/dry-run replay diff modes are not implemented.

## Tools

- [x] Provider-safe `ToolCallEnvelope`.
- [x] ToolRegistry and ToolHarness.
- [x] Core tool specs: `memory_search`, `memory_read`, `working_note`, `skills_list`, `skill_view`, `artifact_update`, `ask_user`.
- [x] Learning tool specs: `memory_write_candidate`, `skill_propose_candidate`, `tool_propose_candidate`, `eval_propose_case`, `learning_discard`.
- [x] Tool calls and results persisted.
- [x] External tools: workspace file search/read/write/patch, HTTP fetch, shell execution, and lightweight browser/app connectors exist.
- [~] Lightweight permission gate for read/write/external/admin exists; denied external/admin calls now create compact `tool_approval` Decision Cards and accepted approvals execute once through ToolHarness; side-effect flags, standing authority, and sandbox profile enforcement are not complete.
- [x] Tool result compression and evidence cards.
- [~] Generated tool lifecycle and evaluation gate: draft candidates, eval result recording, readiness gate, and safe alias installation exist; shadow dry-run, rollback, extension packaging, and richer eval gates are not complete.

## Memory

- [x] Memory candidate writes with evidence/provenance.
- [x] Memory candidate search/read.
- [x] Stable memory is not directly mutated by normal task tools.
- [x] Memory engine pages/indexes beyond candidates.
- [x] Associative recall / LLM Wiki style memory graph.
- [~] Conflict detection, confidence updates, durable tombstones, and compact memory health review cards exist; decay passes, stale review execution, and full selective forgetting are not complete.
- [x] W0 working memory to long-term candidate pipeline.
- [~] DreamCycle idle memory consolidation exists as deterministic candidate promotion and L1 snapshot compilation; it is not yet model-led, scheduled by idle windows, or delta-only across all memory maintenance tasks.
- [~] L1 cache-friendly memory snapshot compile/load exists; daily scheduling and Dream-managed cache invalidation are not complete.
- [~] Memory eval cases and regression gates cover smoke/safety cases, L4 session-search regressions, and a deterministic injection-scan gate; full wrong-memory, over-personalization, and Memory Health gates are not complete.
- [x] L4 cross-session FTS5 search over run user/assistant messages with LIKE fallback and bounded snippets.
- [~] Memory QueryPlanner foundation: deterministic lexical/semantic-style/dimension/temporal planning, route fusion, compact annotations, and CLI debug output exist; vector semantic retrieval, true MMR, tombstone-aware session suppression, and stale decay passes remain.
- [~] Memory tombstone and health foundation: explicit candidate/page tombstones, rejection tombstones, compact health scores/cards, tool calls, and CLI inspection exist; decay passes, stale review execution, private-delete redaction, and full selective forgetting remain.
- [~] Memory write taint tracking and prompt-injection scanner foundation: `memory_write_candidate` and W0 candidate writes append safety evidence, detect prompt override/secret/tool-call injection, and route suspicious writes to review; deeper source-boundary enforcement across MCP/external runtimes remains.

## Skills And Evolution

- [x] Skill draft storage and list/view tools.
- [x] Skill proposal tool exists with generated `SKILL.md` promotion.
- [x] Cross-client skill scanner for `.agents/skills`, `.mnemo/skills`, Claude/Hermes/OpenClaw paths.
- [x] Progressive skill index/summary/full load.
- [x] Skill usage tracking and outcome scoring.
- [~] Skill patch/proposal review lifecycle: proposal, exact patch candidate, eval, review, and promotion gates exist; import/export/update/enable/disable/rollback/doctor/why operations and external shadow-copy lifecycle are not complete.
- [~] SOP crystallization from successful runs exists; provider runtime now builds after-turn learning packets and lets the model propose 0..N mixed memory/skill/tool/eval candidates through native tool calls; local runtime is record-only and background scheduling remains.
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
- [~] Workspace bootstrap blocks for `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, `BOOTSTRAP.md`, `MEMORY.md`, `CLAUDE.md`, and cursor rules load with caps, truncation markers, warning metadata, and prompt-mode filtering; provider cache controls are not complete.
- [x] Prompt modes beyond recorded `full`: `minimal`, `capsule`, and `none` with enforced disclosure boundaries.
- [~] Stable ToolBundle epochs, lazy schema expansion, and a compact `learning.v1` ToolBundle exist for built-in/provider-native tool surfaces; MCP/external large-surface discovery is not complete.

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
- [~] Inline decision cards can render and resolve persisted Inbox decisions, including denied high-risk tool approval requests and compact approved execution results; standing authority is not implemented.
- [x] Event replay/resume with `sinceEventId`.
- [x] Streaming transport API.
- [x] Recall in chat for past work, artifacts, decisions, and knowledge with actionable result cards.
- [~] Learning chips can resolve memory candidates with "以后这样", "这次而已", and reject actions; undo and high-risk confirmation are not implemented.
- [x] Minimal settings drawer for connected apps, permissions, quiet hours, learned preferences, and data controls.
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
- [x] Generic provider capability registry for prompt cache controls, tool bundle epochs, model context limits, and provider-specific fallback modes.

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
- [~] Core SDK / OpenAPI or IDL contract for language-neutral integrations: Python reference `MnemoClient` and `mnemo.core_api.v1` schema exist; HTTP/OpenAPI server bindings and non-Python generated clients are not complete.
- [~] MCP server foundation: dependency-free MCP-style descriptors, direct calls, JSON-RPC over standard Content-Length stdio, JSONL debug mode, and CLI list/call/serve exist for context/update/recall/search/watch/skills/tools/cron/run/replay/eval/status; external packaging remains incomplete.
- [x] Minimal Inbox/Decision persistence tables and CLI/Web API inspection.
- [~] Watch/Cron persistence and scheduled event processing: durable scheduled items, simple schedule grammar, CLI/MCP registration, runtime status, and queue enqueue tick exist; full cron expressions, quiet hours, delivery channels, Sense triggers, and Watch self-learning remain.
- [x] Sessions/messages/L4 search tables and FTS5 indexes for persisted run messages.

## Remaining Trellis Focus

- [x] README reflects current runtime, provider, web, daemon, cancellation, evolution, and harness workflows.
- [~] Implementation checklist now separates runnable foundations from incomplete full-design capabilities.
- [~] Highest-priority core alignment: L4 memory search, Soul/bootstrap prompt input, Inbox/Decision persistence, provider after-turn learning packets, and one-shot high-risk approval execution are implemented; local/background learning reflection and richer frontend recall/learning actions remain.
- [~] Highest-priority integration alignment: SDK/API schema and MCP-style tool server foundations exist; external RuntimeAdapter with context capsule boundaries remains.
- [ ] Extension alignment: Watch/Proactive, Sense/Android, Sub-Agent/AgentCard, richer generated-tool extension packaging, messaging/calendar/mail connectors, and full harness suites.

## Recently Landed Trellis Tasks

- [x] `04-25-scheduled-watch-cron-foundation`: Watch/Cron now persist as lightweight scheduled items, expose CLI/MCP registration, enqueue due runs through the existing daemon queue, and report compact scheduled status.
- [x] `04-25-mcp-content-length-transport`: MCP serve now defaults to standard Content-Length stdio framing while retaining explicit JSONL debug transport, with direct server, CLI, and package smoke coverage.
- [x] `04-25-mcp-server-foundation`: Mnemo now exposes dependency-free MCP-style tool descriptors, direct tool calls, JSON-RPC JSONL stdio, and CLI list/call/serve for compact context/update/recall/search/skills/tools/run/replay/eval/status surfaces.
- [x] `04-25-high-risk-tool-decision-cards`: Denied external/admin tool calls now persist compact `tool_approval` Inbox decisions and stream through the existing inline decision-card path without executing the denied handler.
- [x] `04-25-04-25-approved-tool-approval-execution`: Accepted `tool_approval` Inbox decisions now execute once through ToolHarness and return compact Web/CLI execution metadata.
- [x] `04-25-core-sdk-api-schema-foundation`: Mnemo now exposes a dependency-free Python reference SDK plus `mnemo api schema` for the core context/recall/run/replay/evaluate contract.
- [x] `04-25-implement-after-turn-learning-packet`: Provider runtime now builds a compact after-turn learning packet and lets the model propose 0..N mixed memory/skill/tool/eval candidates through provider-native tool calls.
- [x] `04-25-04-25-refresh-readme-current-capabilities`: README and public runtime wording now describe the current single-chat runtime, provider setup, web UI, daemon, cancellation, memory/skill/tool operations, backup, and validation workflows.
- [x] `04-25-implement-memory-query-planner`: Memory search now produces compact query plans, multi-route fused retrieval, stale/tombstone annotations, tool query-plan metadata, and `mnemo memory search --debug-query`.
- [x] `04-25-implement-memory-tombstone-health`: Memory now has durable tombstones for rejected candidates and explicit page/candidate curation, compact Memory Health reports/cards, provider-native `memory_health_report`/`memory_tombstone` tools, and CLI health/tombstone commands.
- [x] `04-25-implement-memory-write-taint-scanner`: Candidate memory writes now preserve taint/safety evidence, route prompt-injection-like writes to `needs_review:prompt_injection`, reuse shared warning labels, and extend the memory-safety harness with an injection scanner case.
- [x] `04-25-implement-provider-capability-registry`: Provider capability metadata now centralizes prompt cache strategy, ToolBundle adapter epochs, context-window source, fallback modes, CLI inspection, and provider cache-token normalization.
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
- [x] `04-25-implement-inbox-decision-foundation`: persisted Inbox decision items now back `ask_user`, CLI/Web inspection, API resolution, and inline frontend decision actions.
- [x] `04-25-implement-learning-chip-actions`: inline memory learning chips now call a compact Web API to promote, mark this-turn-only, or reject persisted memory candidates.
- [x] `04-25-implement-recall-cards`: `recall_search` now lets the model return compact recall cards for past work, artifacts, decisions, and knowledge, with inline Web actions.
- [x] `04-25-implement-associative-memory-recall`: memory search surfaces one-hop linked active pages through direct and reverse wiki links, and `memory_read` loads stable pages.
- [x] `04-25-implement-cross-client-skill-roots`: default skill roots include workspace/home Claude, Hermes, and OpenClaw skill directories with deterministic de-duplication.
- [x] `04-25-implement-artifact-viewer`: web artifact cards fetch stored artifact bodies on demand through `/api/artifacts` while stream events stay compact.
- [x] `04-25-web-settings-drawer`: Web now has a low-frequency settings drawer backed by compact `/api/settings` summaries and quiet-hours persistence, while normal preference/data actions return to the single composer.
- [x] `04-25-implement-tool-bundle-epochs`: runtime now compiles deterministic ToolBundles, records compact bundle metadata, filters reduced prompt-mode tool profiles, and supports provider-loop schema expansion epochs through `tool_expand_schema`.
