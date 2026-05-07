# Mnemo

Mnemo is a personal AI runtime for a single durable chat surface. It keeps conversation and mission continuity, streams model actions, runs provider-native tools, and turns repeated successful work into evolving memory, skills, and tools.

The repository contains both the design package in `design/` and the runnable implementation in the root `mnemo/` package.

## What Works Today

- Local deterministic runtime for offline development and tests.
- OpenAI-compatible and Anthropic provider runtimes with provider-native tool calls.
- Single-chat web UI with streaming output, actionable artifact cards, decision cards, learning chips, settings drawer, replay, and stop/cancel.
- SQLite state store for conversations, missions, runs, events, memory, skills, artifacts, queue, and generated tools.
- Lightweight tool harness with policy-gated memory, skill, artifact, file, shell, web search/fetch, browser, and app connector tools.
- Memory candidate pipeline, associative memory pages, delta-oriented DreamCycle reports, and L1 memory snapshot.
- Skill scanning, draft/review/promote flow, skill patch candidates, SOP crystallization, and generated tool lifecycle gates.
- Reference SDK and MCP-style tool server for compact external integrations.
- Daemon queue, run cancellation, backup/export/import, replay, and eval harness commands.

## Quick Start

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -e .

mnemo init --state-dir .mnemo
mnemo run "remember: I prefer concise implementation updates" --state-dir .mnemo
mnemo run "remember: stream action cards" --state-dir .mnemo --stream
```

`--stream` emits newline-delimited `ChatEvent` JSON. Non-streaming runs print the response plus `conversation_id`, `mission_id`, and `run_id`; pass those ids back on later turns when you want explicit continuity.

## Provider Runtime

Mnemo reads provider settings from CLI flags, environment variables, or a JSON config file. Prefer `--api-key-env` so secrets do not land in shell history.

```bash
export MNEMO_API_KEY=replace-me

mnemo config smoke \
  --provider openai-compatible \
  --base-url http://localhost:8000/v1 \
  --model local-model \
  --api-key-env MNEMO_API_KEY

mnemo config smoke --stream \
  --provider openai-compatible \
  --base-url http://localhost:8000/v1 \
  --model local-model \
  --api-key-env MNEMO_API_KEY

mnemo run "Summarize the current repo state" \
  --state-dir .mnemo \
  --provider openai-compatible \
  --base-url http://localhost:8000/v1 \
  --model local-model \
  --api-key-env MNEMO_API_KEY \
  --stream
```

Anthropic-compatible runs use the same shape with `--provider anthropic --model <model> --api-key-env <env>`.

## Web Chat

```bash
mnemo web --state-dir .mnemo --port 8765
```

Open `http://127.0.0.1:8765`. The UI is intentionally one chat box: it streams responses, shows tool actions and actionable artifacts inline, preserves the active conversation/mission ids, can replay prior events, exposes low-frequency settings in a drawer, and can stop the current active run through cooperative cancellation.

Provider-backed web runs accept the same provider flags as `mnemo run`.

## Operations

```bash
mnemo daemon enqueue "Draft a project status update" --state-dir .mnemo
mnemo daemon run --state-dir .mnemo --limit 1
mnemo daemon status --state-dir .mnemo

mnemo schedule add --kind cron --message "Run memory maintenance" --schedule daily --state-dir .mnemo
mnemo schedule add --kind watch --target "Rust progress" --instruction "Check blockers and decide whether to notify me" --schedule weekly --state-dir .mnemo
mnemo schedule feedback <watch_id> --outcome no_feedback --action sparsify --policy-schedule weekly --state-dir .mnemo
mnemo schedule list --state-dir .mnemo
mnemo schedule tick --state-dir .mnemo

mnemo runs cancel <run_id> --state-dir .mnemo
mnemo daemon cancel <queue_id> --state-dir .mnemo

mnemo conversations list --state-dir .mnemo
mnemo conversations show <conversation_id> --state-dir .mnemo
mnemo missions list --state-dir .mnemo
mnemo missions show <mission_id> --state-dir .mnemo
mnemo runs list --state-dir .mnemo
mnemo runs show <run_id> --state-dir .mnemo
mnemo events <run_id> --state-dir .mnemo --chat
mnemo replay <run_id> --state-dir .mnemo
mnemo prompt inspect <run_id> --state-dir .mnemo
mnemo artifacts list --state-dir .mnemo
mnemo artifacts read <artifact_id> --state-dir .mnemo
```

## Memory, Skills, And Tools

```bash
mnemo memory notes --state-dir .mnemo
mnemo memory list --state-dir .mnemo
mnemo memory search "implementation preferences" --state-dir .mnemo
mnemo memory read <memory_id> --state-dir .mnemo
mnemo memory links <memory_id> --state-dir .mnemo
mnemo memory snapshot --state-dir .mnemo
mnemo dream run --state-dir .mnemo
mnemo dream status --state-dir .mnemo
mnemo dream report --latest --state-dir .mnemo

mnemo skills scan --state-dir .mnemo
mnemo skills list --state-dir .mnemo
mnemo skills usage writer --state-dir .mnemo
mnemo tools --state-dir .mnemo
mnemo evals create <run_id> "lookup memory smoke" --case-json '{"tool_candidate":"lookup_memory"}' --state-dir .mnemo
mnemo evals list --state-dir .mnemo
mnemo evals record <case_id> passed --result-json '{"ok":true}' --state-dir .mnemo
mnemo tools candidates --state-dir .mnemo
mnemo tools review <candidate_id> --state-dir .mnemo
mnemo tools install <candidate_id> --state-dir .mnemo
mnemo tools uninstall <name> --state-dir .mnemo
mnemo tools rollback <name> --reason "bad activation" --state-dir .mnemo
```

Normal turns do not mutate stable memory directly. They write candidates and working notes; DreamCycle collects a compact delta, exposes a model-facing maintenance plan, persists a report, and uses local consolidation as fallback until provider-led idle runs are wired. Skills and tools follow the same model-directed pattern: propose, evaluate, review, then promote.

## External Integration

```bash
mnemo api schema --json
mnemo api capsule "Ask Codex to inspect this repo" --runtime codex --json
mnemo api external-run "Ask Codex to inspect this repo" \
  --runtime codex \
  --command-json '["python3","external_adapter.py"]' \
  --json
mnemo api serve --state-dir .mnemo --host 127.0.0.1 --port 8765
curl http://127.0.0.1:8765/api/core/schema
curl http://127.0.0.1:8765/api/core/openapi.json
mnemo mcp tools --state-dir .mnemo --json
mnemo mcp config --client claude --state-dir .mnemo --json
mnemo mcp call mnemo_context --state-dir .mnemo --arguments-json '{"intent":"status update"}' --json
mnemo mcp call mnemo_external_run --state-dir .mnemo --arguments-json '{"task":"inspect","command":["python3","external_adapter.py"]}' --json
mnemo mcp serve --state-dir .mnemo
mnemo mcp serve --state-dir .mnemo --transport jsonl
```

The HTTP core API exposes the same compact SDK methods at `/api/core/*` plus `/api/core/openapi.json` for discovery. The MCP-style server exposes compact context, external-runtime capsule, proposal-only external command runs, update, recall, search, skills, tools, watch, watch feedback, cron, run, replay, eval, and status surfaces. `mnemo mcp config` emits secret-free stdio client snippets backed by `mnemo mcp serve`; `serve` defaults to standard MCP stdio `Content-Length` framing; JSONL is kept for local debugging. Watch and cron register durable scheduled items; due items enqueue normal daemon runs so the existing runtime/model decides what to do. Watch feedback lets the model record outcomes and explicitly sparse, pause, or disable noisy proactive checks.

## Backup And Validation

```bash
mnemo backup export --state-dir .mnemo backup.zip
mnemo backup import --state-dir .mnemo-restored backup.zip

python -m unittest discover -s tests
mnemo harness smoke
mnemo harness variants personalization-core --json
mnemo harness release --json
mnemo harness eval proactive-watch --json
mnemo harness eval external-harness --json
mnemo harness list
```

CI also builds the package, installs the wheel outside the checkout, and runs `tests/package_install_smoke.py` to verify the console script, `python -m mnemo`, package metadata, and packaged web assets.

## Acknowledgments

Web tool separation between compact search metadata and page fetch/extraction is acknowledged in `THIRD_PARTY_NOTICES.md`.
