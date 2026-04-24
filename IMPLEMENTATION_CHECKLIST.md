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
- [~] Timeout/retry/cancellation policy.
- [ ] Daemon, queue, single-instance lock, crash recovery.
- [x] Replay harness.

## Tools

- [x] Provider-safe `ToolCallEnvelope`.
- [x] ToolRegistry and ToolHarness.
- [x] Core tool specs: `memory_search`, `memory_read`, `working_note`, `skills_list`, `skill_view`, `artifact_update`, `ask_user`.
- [x] Learning tool specs: `memory_write_candidate`, `skill_propose_candidate`, `tool_propose_candidate`, `eval_propose_case`, `learning_discard`.
- [x] Tool calls and results persisted.
- [~] External tools: workspace file search/read/write, HTTP fetch, and shell execution exist; browser/app connectors and patch-specialized tools remain.
- [x] Lightweight permission gate for read/write/external/admin.
- [x] Tool result compression and evidence cards.
- [~] Generated tool lifecycle and evaluation gate: draft candidates, eval result recording, and readiness gate exist; generated tool installation remains pending.

## Memory

- [x] Memory candidate writes with evidence/provenance.
- [x] Memory candidate search/read.
- [x] Stable memory is not directly mutated by normal task tools.
- [x] Memory engine pages/indexes beyond candidates.
- [~] Associative recall / LLM Wiki style memory graph.
- [x] Conflict detection and confidence updates.
- [x] W0 working memory to long-term candidate pipeline.
- [x] DreamCycle idle memory consolidation.
- [x] Daily compiled L1 cache-friendly memory snapshot.
- [x] Memory eval cases and regression gates.

## Skills And Evolution

- [x] Skill draft storage and list/view tools.
- [x] Skill proposal tool exists with generated `SKILL.md` promotion.
- [~] Cross-client skill scanner for `.agents/skills`, `.mnemo/skills`, Claude/Hermes/OpenClaw paths.
- [x] Progressive skill index/summary/full load.
- [x] Skill usage tracking and outcome scoring.
- [~] Skill patch/proposal review lifecycle: proposal review gate exists; patch-specific diff/apply remains pending.
- [x] SOP crystallization from successful runs.
- [x] Skill eval harness.

## Prompt And Context

- [x] Runtime records `prompt.assembled` metadata.
- [x] PromptBlock model.
- [x] PromptAssembler with stable prefix and dynamic tail.
- [~] Tool card/schema budget separation.
- [x] Skill and memory progressive disclosure.
- [x] KV-cache-first prompt assembly ordering.
- [x] Prompt inspection command.
- [x] Context compression.

## Frontend Experience

- [x] Backend `ChatEvent` stream contract started.
- [x] Action and learning events are representable in stream.
- [x] User-facing single-chat web frontend.
- [x] Universal composer.
- [x] Inline action cards.
- [~] Inline artifact cards and artifact viewer.
- [x] Inline decision cards.
- [~] Event replay/resume with `sinceEventId`.
- [x] Streaming transport API.

## Provider And Model Integration

- [x] Provider adapter boundary exists.
- [x] OpenAI-compatible chat completions adapter.
- [ ] Anthropic adapter.
- [x] Provider config from environment/CLI without persisting secrets.
- [x] Model/tool loop with provider-native tool call schema.
- [x] Streaming response parser.
- [x] Provider error normalization.
- [~] Local endpoint smoke command using user-provided credentials.

## Evaluation And Harness

- [x] Basic unit tests.
- [x] Golden personalization cases.
- [x] Runtime smoke replay tests.
- [x] Memory safety tests.
- [ ] Skill evolution tests.
- [x] Provider fake server tests.
- [ ] CLI and package install tests in CI.

## Persistence And Operations

- [x] SQLite schema creation.
- [x] State dirs for wiki, skills, runs, artifacts.
- [x] Schema migrations.
- [x] JSONL trace mirror.
- [x] Event outbox.
- [x] Config file and env override model.
- [ ] Daemon status command.
- [x] Backup/export/import.

## Current Trellis Focus

- [x] `04-24-implement-provider-backed-runtime`: OpenAI-compatible provider config, adapter, runtime bridge, CLI selection, timeout errors, and fake-server tests implemented.
- [~] `04-24-implement-prompt-assembly-foundation`: PromptBlock, PromptAssembler, provider runtime integration, and prompt inspect CLI are in progress.
- [~] `04-24-implement-memory-engine-foundation`: memory pages, promotion/rejection, stable search, and deterministic DreamCycle are in progress.
- [~] `04-24-implement-skills-filesystem-lifecycle`: Agent Skills scanner, skill service, and generated `SKILL.md` promotion are in progress.
- [x] `04-24-implement-event-replay-foundation`: JSONL trace mirror, event replay CLI, and trace summary are implemented.
- [~] `04-24-implement-tool-boundary-cards`: Tool permission policy, compact model tool results, and evidence cards are in progress.
- [~] `04-24-implement-prompt-progressive-context`: Memory/skill compact indexes and runtime prompt injection are in progress.
- [~] `04-25-implement-openai-streaming-provider`: OpenAI-compatible SSE parser, streamed deltas, and streamed tool-call chunks are in progress.
- [~] `04-25-implement-skills-metadata-compatibility`: common Agent Skills metadata parsing and compact card projection are in progress.
- [~] `04-25-implement-single-chat-web-frontend`: stdlib web server, single chat UI, NDJSON stream transport, and replay endpoint are in progress.
- [~] `04-25-implement-eval-harness-foundation`: built-in personalization golden cases, smoke suite, and replay harness CLI are in progress.
- [~] `04-25-implement-config-resolver`: shared runtime config resolver, redacted inspect CLI, and provider config refactor are in progress.
- [x] `04-25-implement-standard-local-tools-foundation`: workspace-scoped file tools, policy-gated web fetch, and policy-gated shell execution are implemented.
- [x] `04-25-implement-prompt-context-compression`: prompt token budget, optional block dropping, checkpoint compaction, and dropped-block metadata are implemented.
- [x] `04-25-implement-memory-conflict-reinforcement`: duplicate reinforcement, conflict review routing, and memory link provenance are implemented.
- [x] `04-25-implement-skill-usage-scoring`: skill usage events, outcome scoring, compact card stats, and deterministic skill ranking are implemented.
- [~] `04-25-implement-tool-candidate-eval-gate`: tool candidate status lifecycle, eval result recording, and readiness review gate are implemented.
- [x] `04-25-implement-daily-l1-memory-snapshot`: daily compact active-memory snapshot compilation, prompt injection, and runtime loading are implemented.
- [x] `04-25-implement-w0-working-memory-pipeline`: model-marked working notes can enter DreamCycle as candidate-first memory updates.
- [~] `04-25-implement-skill-review-lifecycle`: generated skill candidates can be reviewed to `ready` or `blocked:*` before explicit promotion.
- [x] `04-25-implement-skill-eval-harness`: linked skill eval cases can run, persist pass/fail results, and gate skill review.
- [x] `04-25-implement-sop-crystallization-from-runs`: completed runs with successful compact tool traces can become draft skill candidates without raw payload leakage.
- [x] `04-25-implement-memory-safety-evals`: deterministic memory safety harness suite covers candidate-first writes, conflict guardrails, compact payloads, and duplicate reinforcement.
- [x] `04-25-implement-sqlite-schema-migrations`: SQLite migration ledger, schema version API, idempotent initialization, and legacy column upgrades are implemented.
- [x] `04-25-implement-event-outbox`: SQLite outbox migration, run-event mirroring, enqueue/list/mark APIs, and storage tests are implemented.
- [x] `04-25-implement-backup-export-import`: zip state backup, validated import/replace, CLI commands, and round-trip safety tests are implemented.
