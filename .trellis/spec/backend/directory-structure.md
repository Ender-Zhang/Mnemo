# Directory Structure

## Scenario: Root Package Backend Layout

### 1. Scope / Trigger
- Trigger: adding backend modules, moving runtime/provider/tool code, or adding CLI/web APIs.
- Goal: keep the project in the root `mnemo/` package layout and avoid reintroducing a `src/` tree.

### 2. Directory Layout
```text
mnemo/
  core/        shared dataclasses, config, errors, ids, JSON helpers
  storage/     SQLite StateStore and migrations
  runtime/     local/provider runtimes, daemon, ledger, stream projection
  providers/   OpenAI-compatible and Anthropic adapter boundary
  tools/       ToolRegistry, ToolHarness, standard tools, tool evolution
  memory/      memory pages, candidates, DreamCycle, associative recall
  skills/      skill scanning, service lifecycle, generated SKILL.md writes
  prompt/      PromptBlock and PromptAssembler
  evals/       deterministic harness suites
  interfaces/  CLI and stdlib web server/static assets
tests/         unittest test suite mirrored by behavior area
design/        design package, not runtime code
```

### 3. Contracts
- New importable backend code goes under `mnemo/`, not `src/`.
- CLI commands belong in `mnemo/interfaces/cli.py`; HTTP routes belong in `mnemo/interfaces/web.py`.
- Durable state changes belong in `mnemo/storage/sqlite.py` and the database spec must be updated.
- Provider protocol normalization belongs in `mnemo/providers/base.py`; runtime orchestration stays in `mnemo/runtime/provider.py`.
- Tool specs and handlers belong in `mnemo/tools/registry.py` or `mnemo/tools/standard.py`.
- Domain services should stay close to their domain: memory in `mnemo/memory/`, skills in `mnemo/skills/`, prompt in `mnemo/prompt/`.
- Tests use stdlib `unittest` and live in `tests/test_<area>.py`.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| Package import | `python -m mnemo --version` works from source and installed wheel | `tests/package_install_smoke.py` |
| New CLI command | Parser, command handler, and tests live in CLI area | `tests/test_cli.py` |
| New persisted field | Storage migration and spec updated together | `tests/test_storage.py` |
| New provider behavior | Adapter tests use fake local HTTP servers | `tests/test_providers.py` |

### 5. Good/Base/Bad Cases
- Good: add a provider feature in `mnemo/providers/base.py` and cover it in `tests/test_providers.py`.
- Good: expose a tool by adding a `ToolSpec`, handler, compact summary/evidence, and harness tests.
- Base: small domain helpers can live in `mnemo/core/` when they are shared by multiple packages.
- Bad: adding `src/` or duplicating an existing domain service in `interfaces/`.
- Bad: putting storage SQL inside CLI/web handlers.

### 6. Tests Required
- Source unit tests must pass with `python -m unittest discover -s tests`.
- Package-affecting changes must keep install smoke passing.
