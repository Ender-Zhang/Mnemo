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
- [~] Daemon, queue, single-instance lock, stale queue recovery, scheduled watch/cron enqueue, scheduled Dream maintenance, and model-marked W0 pending recovery foundations exist; full Supervisor priority classes, Inbox recovery, Watch recovery, and child runtime cleanup are not complete.
- [~] Replay harness supports deterministic trace/store checks, dry-run reconstruction, safe read-only live-tools drift checks, and compact run-to-run category diffs; full side-effecting live tool replay remains intentionally skipped.

## Tools

- [x] Provider-safe `ToolCallEnvelope`.
- [x] ToolRegistry and ToolHarness.
- [x] Core tool specs: `memory_search`, `memory_read`, `working_note`, `skills_list`, `skill_view`, `artifact_update`, `ask_user`.
- [x] Learning tool specs: `memory_write_candidate`, `skill_propose_candidate`, `tool_propose_candidate`, `eval_propose_case`, `learning_discard`.
- [x] Tool calls and results persisted.
- [x] External tools: workspace file search/read/write/patch, HTTP fetch, shell execution, and lightweight browser/app connectors exist.
- [~] Lightweight permission gate for read/write/external/admin exists; default runtime policy allows all built-in risk levels for smoother single-chat execution, while explicitly stricter policies can still create compact `tool_approval` Decision Cards with natural labels and accepted approvals execute once through ToolHarness; side-effect flags and sandbox profile enforcement are not complete.
- [x] Tool result compression and evidence cards.
- [x] User file operations default to a per-state user workspace at `<state-dir>/workspace` instead of the process cwd or source repository root.
- [~] Generated tool lifecycle and evaluation gate: draft candidates, eval result recording, readiness gate, safe alias installation, and explicit rollback exist; shadow dry-run, extension packaging, and richer eval gates are not complete.

## Memory

- [x] Memory candidate writes with evidence/provenance.
- [x] Memory candidate search/read.
- [x] Stable memory is not directly mutated by normal task tools.
- [x] Memory engine pages/indexes beyond candidates.
- [x] Associative recall / LLM Wiki style memory graph, including persisted `memory_links` plus active-page metadata `aliases`, `links`, and `associations`.
- [x] Candidate safety/quality signals, conflict detection, exact/near-duplicate reinforcement, confidence updates, durable tombstones, private-delete redaction, low-usefulness archival, replacement links, harmful eval routing, compact memory health review cards, and metadata-driven decay/stale marking exist.
- [x] W0 working memory to long-term candidate pipeline.
- [~] DreamCycle idle memory consolidation now collects compact deltas, records model-facing maintenance plans, applies explicit model-proposed memory maintenance actions, persists compact applied/skipped results, supports lightweight scheduled Dream ticks, and limits local fallback to delta candidates; richer provider-led idle heuristics remain incomplete.
- [~] L1 cache-friendly memory snapshot compile/load exists with active summaries, alias pointers, and association hubs, and scheduled Dream ticks refresh it through normal Dream execution; fine-grained cache invalidation remains incomplete.
- [x] Memory eval cases and regression gates cover smoke/safety cases, L4 session-search regressions, injection-scan, wrong-memory tombstone suppression, low-confidence over-personalization no-promotion, and compact Memory Health gates.
- [x] L4 cross-session FTS5 search over run user/assistant messages with LIKE fallback and bounded snippets.
- [~] Memory QueryPlanner foundation: deterministic lexical/semantic-style/dimension/temporal planning, route fusion, compact annotations, tombstone-aware session suppression, and CLI debug output exist; vector semantic retrieval and true MMR remain.
- [x] Memory tombstone and health foundation: explicit candidate/page tombstones, rejection tombstones, private-delete redaction, low-usefulness archive, replacement links, harmful eval routing, compact health scores/cards, metadata-driven decay/stale marking, tool calls, and CLI inspection exist.
- [~] Memory write taint tracking and prompt-injection scanner foundation: `memory_write_candidate` and W0 candidate writes append safety evidence, detect prompt override/secret/tool-call injection, and route suspicious writes to review; deeper source-boundary enforcement across MCP/external runtimes remains.

## Skills And Evolution

- [x] Skill draft storage and list/view tools.
- [x] Skill proposal tool exists with generated `SKILL.md` promotion.
- [x] Cross-client skill scanner for `.agents/skills`, `.mnemo/skills`, Claude/Hermes/OpenClaw paths.
- [x] Progressive skill index/summary/full load.
- [x] Skill usage tracking and outcome scoring.
- [~] Skill patch/proposal review lifecycle: proposal, exact patch candidate, eval, review, and promotion gates exist; import/export/update/enable/disable/rollback/doctor/why operations and external shadow-copy lifecycle are not complete.
- [~] SOP crystallization from successful runs exists; provider runtime now builds after-turn learning packets and lets the model propose 0..N mixed memory/skill/tool/eval candidates through native tool calls after a structure-only evidence gate; local runtime is record-only and background scheduling remains.
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
- [x] Web chat assistant output renders safe DOM-built Markdown after streaming/replay.
- [x] Web chat replays historical user prompts from `turn.started` and shows compact browser continuity context.
- [x] Web activity panel de-duplicates action lifecycle updates into stable rows.
- [x] Web activity hides internal learning housekeeping such as after-turn learning tool events, `learning_discard`, and learning-tone status updates.
- [x] Web composer sends on Enter, preserves Shift+Enter newline, and shows a volatile "回复中" pending assistant indicator while waiting for model output.
- [x] Web tool action cards show compact call arguments and completed results in one card while suppressing duplicate tool-result source cards.
- [x] Recall in chat for past work, artifacts, decisions, and knowledge with actionable result cards.
- [x] Recall result cards compact repeated title/summary text.
- [x] Ordinary learning candidates stay unobtrusive; exceptional review-gated memory chips can resolve with "记住", "仅本次", "忽略", and undo actions.
- [x] Minimal settings drawer for connected apps, permissions, quiet hours, learned preferences, ten-dimensional memory inspection, and data controls.
- [~] Artifact operations beyond open/view: web artifact cards now support continue edit, export, compare related artifacts, send draft, and diff apply/revert composer intents; direct apply/revert/send execution remains tool/model-led.

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
- [~] Harness gates exist as built-in smoke suites with core variant comparison (`no_memory`, `skills_only`, `full_mnemo`), quantitative thresholds, external-harness/proactive-watch suites, and a compact release gate report; broader red-team and multi-profile harnesses remain incomplete.

## Persistence And Operations

- [x] SQLite schema creation.
- [x] State dirs for wiki, skills, runs, artifacts.
- [x] Schema migrations.
- [x] JSONL trace mirror.
- [x] Event outbox.
- [x] Config file and env override model.
- [x] Daemon status command.
- [x] Backup/export/import.
- [~] Core SDK / OpenAPI or IDL contract for language-neutral integrations: Python reference `MnemoClient`, `mnemo.core_api.v1` schema, proposal-only command `external_run`, Dream/Watch/Cron schedule registration, compact runtime status, stdlib HTTP JSON API, and compact OpenAPI discovery exist; non-Python generated clients are not complete.
- [~] MCP server foundation: dependency-free MCP-style descriptors, direct calls, JSON-RPC over standard Content-Length stdio, JSONL debug mode, CLI list/config/call/serve, and compact client config snippets exist for context/capsule/external-run/update/recall/search/watch/watch-feedback/skills/tools/cron/dream-schedule/run/replay/eval/status; published external packaging remains incomplete.
- [x] Minimal Inbox/Decision persistence tables and CLI/Web API inspection.
- [~] Watch/Cron/Dream persistence and scheduled event processing: durable scheduled items, simple schedule grammar, CLI/MCP/SDK/HTTP registration for Dream/Watch/Cron, runtime status, queue enqueue tick, direct Dream maintenance tick, and model-supplied Watch feedback policy exist; full cron expressions, quiet hours, delivery channels, Sense triggers, and richer Watch self-learning remain.
- [x] Sessions/messages/L4 search tables and FTS5 indexes for persisted run messages.

## Remaining Trellis Focus

- [x] README reflects current runtime, provider, web, daemon, cancellation, evolution, and harness workflows.
- [~] Implementation checklist now separates runnable foundations from incomplete full-design capabilities.
- [~] Highest-priority core alignment: L4 memory search, Soul/bootstrap prompt input, Inbox/Decision persistence, provider after-turn learning packets, and one-shot high-risk approval execution are implemented; local/background learning reflection and richer frontend recall/learning actions remain.
- [~] Highest-priority integration alignment: SDK/API schema, MCP-style tool server, external context capsule boundaries, and a proposal-only command RuntimeAdapter foundation exist; OpenClaw/Codex/ACP-specific adapters remain.
- [ ] Extension alignment: Watch/Proactive, Sense/Android, Sub-Agent/AgentCard, richer generated-tool extension packaging, messaging/calendar/mail connectors, and full harness suites.

## Recently Landed Trellis Tasks

- [x] `04-30-memory-quality-signal`: Memory candidate writes now attach compact quality scores for specificity, personalization, persistence, actionability, and verifiability, and Dream fallback rejects explicit discard-quality candidates before stable-page promotion.
- [x] `04-30-unobtrusive-learning-confirmations`: Normal memory/skill/tool/eval learning candidates now persist silently without visible confirmation chips, after-turn learning action events are marked internal for Web suppression, and rare decision cards use natural option labels.
- [x] `04-30-memory-near-duplicate-reinforcement`: Dream consolidation now treats conservative same-dimension, same-polarity near-duplicate candidates as reinforcement of existing active pages, preventing paraphrased stable memories from duplicating.
- [x] `04-29-memory-l1-association-index`: L1 memory snapshots now compile compact alias pointers and association hubs from active pages, metadata associations, and memory links, and prompt/query planning can use those low-token routes before reading full pages.
- [x] `04-29-memory-wiki-metadata-associations`: Memory recall now resolves active wiki metadata aliases, links, and associations, materializes them into compact markdown frontmatter, carries `why_relevant` into linked context cards, and counts metadata connections in memory health.
- [x] `04-28-default-open-tool-policy`: Default ToolExecutionPolicy now allows read/write/external/admin risks so normal Web runs do not stall on approval cards; explicit stricter policies still exercise the tool approval path.
- [x] `04-28-learning-debt-review`: Provider learning now reviews compact recent-turn packets after several completed turns without learning candidates, using the existing `learning.v1` tools and a debt-review barrier to avoid repeated low-signal reflection.
- [x] `04-28-redesign-polished-chat-shell`: Web UI now uses a darker product shell, calmer light chat surface, responsive composer, compact context/activity panels, and desktop/mobile-validated layouts while preserving the single-chat interaction model.
- [x] `04-28-default-user-workspace`: Local file/shell tools, Web, SDK, MCP, and live replay now resolve missing workspace roots to `<state-dir>/workspace`, preventing user-generated files from landing in the source repo by default.
- [x] `04-27-polish-chat-interactions-memory-view`: Web chat now sends on Enter, shows a pending assistant indicator, consolidates tool call/result details into one card, suppresses duplicate tool-result source cards, compacts recall duplication, and exposes ten-dimensional memory inspection from settings.
- [x] `04-27-skip-low-signal-learning-reflection`: Provider after-turn learning now uses a structure-only evidence gate, skips zero/low-tool turns without a second model call, and hides internal learning housekeeping from Web Activity.
- [x] `04-27-polish-reference-frontend-markdown`: Web UI now more closely follows the generated reference with labeled rail navigation, compact user context, de-duplicated activity rows, replayed user prompts, and safe DOM-built Markdown rendering for assistant messages.
- [x] `04-27-redesign-single-chat-frontend`: Web UI now uses a polished single-chat shell with rail navigation, contextual activity panel, refined composer affordances, and preserved inline action/decision/learning/artifact/recall rendering.
- [x] `04-27-memory-harmful-eval-routing`: Harmful memory tombstones now create compact draft memory-core eval cases through MemoryEngine, CLI, and ToolHarness when run provenance is available.
- [x] `04-27-memory-selective-forgetting-policy`: `memory_tombstone` now supports low-usefulness archival plus optional replacement links/metadata across MemoryEngine, CLI, ToolHarness, and tests.
- [x] `04-27-memory-dream-maintenance-actions`: DreamCycle now applies explicit model-proposed memory tombstone/decay actions, supports native-style tool-call shapes, persists compact applied/skipped action results, and keeps local fallback delta-bounded.
- [x] `04-27-dream-scheduled-maintenance`: Scheduler now supports `dream` scheduled items that run bounded Dream maintenance, persist compact report cards, refresh L1 snapshots through normal Dream execution, and expose CLI creation/tick coverage.
- [x] `04-27-mcp-dream-schedule-surface`: MCP now exposes `mnemo_dream_schedule` as a compact facade over `ScheduleService.add_dream`, with direct call, CLI mcp call, runtime status, and scheduler tick coverage.
- [x] `04-27-core-api-dream-schedule-surface`: SDK and HTTP Core API now expose `schedule_dream` as a compact facade over `ScheduleService.add_dream`, with schema/OpenAPI, CLI schema, Web dispatch, and SDK tests.
- [x] `04-27-core-api-runtime-status-surface`: SDK and HTTP Core API now expose compact read-only `runtime_status`, and MCP runtime status routes through the same SDK method.
- [x] `04-27-core-api-watch-cron-schedule-surface`: SDK and HTTP Core API now expose compact `schedule_watch` and `schedule_cron` facades over `ScheduleService` without changing scheduler execution semantics.
- [x] `04-27-replay-harness-diff-modes`: replay reports now expose deterministic, dry-run, and safe live-tools modes with compact prompt/tool/memory/skill/output diffs.
- [x] `04-27-daemon-w0-pending-recovery`: daemon status now reports model-marked W0 backlog, and daemon recover/run flush those notes through MemoryEngine without mutating ephemeral notes.
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
- [x] `04-25-04-25-expose-tool-evolution-cli`: CLI now exposes tool candidate listing, review, install, generated-tool uninstall, and generated-tool rollback through the existing ToolEvolutionService lifecycle.
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
- [x] `04-25-web-artifact-actions`: Web artifact cards now expose continue/export/compare/send/apply/revert actions, use compact related artifact metadata, and route side-effectful work back through the single composer.
- [x] `04-25-implement-tool-bundle-epochs`: runtime now compiles deterministic ToolBundles, records compact bundle metadata, filters reduced prompt-mode tool profiles, and supports provider-loop schema expansion epochs through `tool_expand_schema`.
- [x] `04-25-dream-maintenance-interface`: DreamCycle now exposes compact delta collection, model-facing maintenance plans, persisted reports, `dream status/report`, and delta-limited local fallback consolidation.
- [x] `04-25-harness-variant-report`: Harness now compares `no_memory`/`skills_only`/`full_mnemo` variants with compact metrics and gates, exposed through CLI, SDK, and MCP eval surfaces.
- [x] `04-25-external-runtime-context-capsule`: SDK/CLI/MCP now build minimal-disclosure external runtime context capsules, and the external-harness eval verifies capsule boundaries.
- [x] `04-27-harness-release-gate-report`: Harness now aggregates personalization variant gates plus memory-safety, skill-evolution, and external-harness suites into a compact release report across CLI, SDK, and MCP.
- [x] `04-27-proactive-watch-feedback-gates`: Watch feedback now records compact outcomes and applies explicit model/user policy decisions through ScheduleService, exposed via CLI/MCP/provider tools and covered by the proactive-watch harness suite.
- [x] `04-27-external-command-runtime-adapter`: Mnemo now executes explicit external command runtimes through fresh context capsules, records proposal-only RunLedger events, ignores unsupported direct-write fields as boundary violations, and exposes the foundation through SDK/CLI/MCP plus external-harness coverage.
- [x] `04-27-mcp-config-packaging-foundation`: MCP integration now exposes compact generic/Claude stdio client config snippets through `mnemo.mcp.mcp_server_config` and `mnemo mcp config`, with package smoke coverage.
- [x] `04-27-http-core-api-foundation`: Mnemo now serves the core SDK contract over dependency-free HTTP JSON routes with compact OpenAPI discovery and CLI `mnemo api serve`, covered by web/CLI/package smoke tests.
- [x] `04-27-generated-tool-rollback-foundation`: Generated tools now expose an explicit rollback lifecycle through `ToolEvolutionService`, provider-native `tool_rollback_generated`, and `mnemo tools rollback`, marking both generated tool and candidate as `rolled_back`.
- [x] `04-27-learning-chip-undo-foundation`: Inline memory learning chips can undo accepted learning by tombstoning the promoted page and candidate through existing memory curation records.
- [x] `04-27-learning-chip-high-risk-confirmation`: Review-gated memory candidates now stream compact confirmation metadata and render as explicit inline learning confirmations without a separate workflow.
- [x] `04-27-memory-decay-stale-foundation`: Memory pages now round-trip maintenance metadata, health reports surface decay-due cards, and `memory_decay_stale_pages` / `mnemo memory decay` can mark expired or sufficiently decayed active pages stale.
- [x] `04-27-tombstone-aware-session-recall`: L4 session recall now suppresses tombstone-matching snippets by default, exposes compact recall-policy metadata, and supports explicit historical lookup through `include_tombstoned`.
- [x] `04-27-memory-private-delete-redaction`: Private-delete now redacts page/candidate text and evidence, writes minimal hash tombstones, suppresses source-run L4 snippets, and is exposed through `mnemo memory forget` plus `memory_private_delete`.
