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
- [x] Daemon, queue, single-instance lock, crash recovery.
- [x] Replay harness.

## Tools

- [x] Provider-safe `ToolCallEnvelope`.
- [x] ToolRegistry and ToolHarness.
- [x] Core tool specs: `memory_search`, `memory_read`, `working_note`, `skills_list`, `skill_view`, `artifact_update`, `ask_user`.
- [x] Learning tool specs: `memory_write_candidate`, `skill_propose_candidate`, `tool_propose_candidate`, `eval_propose_case`, `learning_discard`.
- [x] Tool calls and results persisted.
- [x] External tools: workspace file search/read/write/patch, HTTP fetch, shell execution, and lightweight browser/app connectors exist.
- [x] Lightweight permission gate for read/write/external/admin.
- [x] Tool result compression and evidence cards.
- [x] Generated tool lifecycle and evaluation gate: draft candidates, eval result recording, readiness gate, and safe alias installation exist.

## Memory

- [x] Memory candidate writes with evidence/provenance.
- [x] Memory candidate search/read.
- [x] Stable memory is not directly mutated by normal task tools.
- [x] Memory engine pages/indexes beyond candidates.
- [x] Associative recall / LLM Wiki style memory graph.
- [x] Conflict detection and confidence updates.
- [x] W0 working memory to long-term candidate pipeline.
- [x] DreamCycle idle memory consolidation.
- [x] Daily compiled L1 cache-friendly memory snapshot.
- [x] Memory eval cases and regression gates.

## Skills And Evolution

- [x] Skill draft storage and list/view tools.
- [x] Skill proposal tool exists with generated `SKILL.md` promotion.
- [x] Cross-client skill scanner for `.agents/skills`, `.mnemo/skills`, Claude/Hermes/OpenClaw paths.
- [x] Progressive skill index/summary/full load.
- [x] Skill usage tracking and outcome scoring.
- [x] Skill patch/proposal review lifecycle: proposal, exact patch candidate, eval, review, and promotion gates exist.
- [x] SOP crystallization from successful runs.
- [x] Skill eval harness.

## Prompt And Context

- [x] Runtime records `prompt.assembled` metadata.
- [x] PromptBlock model.
- [x] PromptAssembler with stable prefix and dynamic tail.
- [x] Tool card/schema budget separation.
- [x] Skill and memory progressive disclosure.
- [x] KV-cache-first prompt assembly ordering.
- [x] Prompt inspection command.
- [x] Context compression.

## Frontend Experience

- [x] Backend `ChatEvent` stream contract started.
- [x] Action and learning events are representable in stream.
- [x] User-facing single-chat web frontend.
- [x] Universal composer.
- [x] Busy-state stop/cancel control in the single composer.
- [x] Stop control targets the current active run rather than replay state.
- [x] New/reset is guarded while a run is streaming.
- [x] Inline action cards.
- [x] Inline artifact cards and artifact viewer.
- [x] Inline decision cards.
- [x] Event replay/resume with `sinceEventId`.
- [x] Streaming transport API.

## Provider And Model Integration

- [x] Provider adapter boundary exists.
- [x] OpenAI-compatible chat completions adapter.
- [x] Anthropic adapter.
- [x] Provider config from environment/CLI without persisting secrets.
- [x] Model/tool loop with provider-native tool call schema.
- [x] Streaming response parser.
- [x] Provider error normalization.
- [x] Local endpoint smoke command using user-provided credentials.

## Evaluation And Harness

- [x] Basic unit tests.
- [x] Golden personalization cases.
- [x] Runtime smoke replay tests.
- [x] Memory safety tests.
- [x] Skill evolution tests.
- [x] Provider fake server tests.
- [x] Standard tool edge regression tests for binary file reads and shell timeouts.
- [x] CLI and package install tests in CI.

## Persistence And Operations

- [x] SQLite schema creation.
- [x] State dirs for wiki, skills, runs, artifacts.
- [x] Schema migrations.
- [x] JSONL trace mirror.
- [x] Event outbox.
- [x] Config file and env override model.
- [x] Daemon status command.
- [x] Backup/export/import.

## Remaining Trellis Focus

- [x] No known checklist gaps after the browser/app connector task.
- [x] README reflects current runtime, provider, web, daemon, cancellation, evolution, and harness workflows.

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
- [x] `04-25-implement-associative-memory-recall`: memory search surfaces one-hop linked active pages through direct and reverse wiki links, and `memory_read` loads stable pages.
- [x] `04-25-implement-cross-client-skill-roots`: default skill roots include workspace/home Claude, Hermes, and OpenClaw skill directories with deterministic de-duplication.
- [x] `04-25-implement-artifact-viewer`: web artifact cards fetch stored artifact bodies on demand through `/api/artifacts` while stream events stay compact.
