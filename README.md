# Mnemo

Mnemo is a personal AI runtime for a single durable chat surface. It keeps conversation and mission continuity, streams model actions, runs provider-native tools, and turns repeated successful work into evolving memory, skills, and tools.

The repository contains both the design package in `design/` and the runnable implementation in the root `mnemo/` package.

## What Works Today

- Local deterministic runtime for offline development and tests.
- OpenAI-compatible and Anthropic provider runtimes with provider-native tool calls.
- Single-chat web UI with streaming output, action cards, artifact cards, decision cards, learning chips, replay, and stop/cancel.
- SQLite state store for conversations, missions, runs, events, memory, skills, artifacts, queue, and generated tools.
- Lightweight tool harness with policy-gated memory, skill, artifact, file, shell, HTTP, browser, and app connector tools.
- Memory candidate pipeline, associative memory pages, DreamCycle consolidation, and daily L1 memory snapshot.
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

Open `http://127.0.0.1:8765`. The UI is intentionally one chat box: it streams responses, shows tool actions and artifacts inline, preserves the active conversation/mission ids, can replay prior events, and can stop the current active run through cooperative cancellation.

Provider-backed web runs accept the same provider flags as `mnemo run`.

## Operations

```bash
mnemo daemon enqueue "Draft a project status update" --state-dir .mnemo
mnemo daemon run --state-dir .mnemo --limit 1
mnemo daemon status --state-dir .mnemo

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
```

Normal turns do not mutate stable memory directly. They write candidates and working notes; DreamCycle consolidates them into durable memory pages and cache-friendly snapshots. Skills and tools follow the same model-directed pattern: propose, evaluate, review, then promote.

## External Integration

```bash
mnemo api schema --json
mnemo mcp tools --state-dir .mnemo --json
mnemo mcp call mnemo_context --state-dir .mnemo --arguments-json '{"intent":"status update"}' --json
mnemo mcp serve --state-dir .mnemo
```

The MCP-style server exposes compact context, update, recall, search, skills, tools, run, replay, eval, and status surfaces. Watch and cron tools are listed as deferred surfaces until durable scheduling lands.

## Backup And Validation

```bash
mnemo backup export --state-dir .mnemo backup.zip
mnemo backup import --state-dir .mnemo-restored backup.zip

python -m unittest discover -s tests
mnemo harness smoke
mnemo harness list
```

CI also builds the package, installs the wheel outside the checkout, and runs `tests/package_install_smoke.py` to verify the console script, `python -m mnemo`, package metadata, and packaged web assets.
