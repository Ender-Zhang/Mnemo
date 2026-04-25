# Provider Capability Contracts

## Scenario: Provider Capability Registry

### 1. Scope / Trigger
- Trigger: changes to provider adapters, runtime provider metadata, config inspection,
  prompt cache strategy, or ToolBundle adapter-version selection.
- Goal: keep provider-specific cache/tool/context assumptions in one compact registry without adding workflow routing.

### 2. Signatures
- `provider_capabilities(provider: str, *, model: str | None = None) -> ProviderCapabilities`
- `provider_capabilities_for_adapter(adapter: Any) -> ProviderCapabilities`
- `ProviderCapabilities.metadata() -> dict[str, Any]`
- `ProviderCapabilities.cache_plan(tool_bundle: Mapping[str, Any] | None = None) -> dict[str, Any]`
- `usage_cache_metrics(provider: str, usage: Mapping[str, Any]) -> dict[str, int]`
- CLI: `mnemo config capabilities [--provider local|openai-compatible|anthropic] [--model MODEL] [--json]`

### 3. Contracts
- The registry is descriptive metadata, not a workflow router.
- Runtime code uses `ProviderCapabilities.adapter_version` when building `ToolBundle` objects.
- `prompt.assembled` events include compact `provider_capabilities` and `cache_plan` objects.
- Provider request metadata includes compact `provider_capabilities` and `cache_plan` objects for harness inspection.
- After-turn learning reflection provider requests include `stage="after_turn_learning"`, compact `provider_capabilities`, and compact `cache_plan`.
- `cache_plan.tool_bundle` includes only ToolBundle metadata, not raw schemas.
- Unknown providers get conservative capabilities and keep native tool calls enabled.
- OpenAI-compatible providers use automatic prefix cache metadata and stable ToolBundle IDs.
- Anthropic providers expose cache-control surfaces in metadata; actual cache-control injection remains adapter-owned.
- OpenAI and Anthropic completion metadata normalize provider cache token usage into `cache_metrics`.
- CLI capability output must redact secrets through `RuntimeConfig.redacted()`.

### 4. Validation & Error Matrix
| Case | Expected Behavior | Test Point |
| --- | --- | --- |
| OpenAI-compatible capability lookup | Adapter version is `openai.v1`; strategy is `automatic_prefix` | `tests/test_providers.py` |
| Anthropic capability lookup | Adapter version is `anthropic.v1`; cache surfaces include tools | `tests/test_providers.py` |
| Unknown provider lookup | Conservative metadata is returned without raising | `tests/test_providers.py` |
| Runtime prompt assembly | Ledger stores compact capabilities and cache plan | `tests/test_runtime.py` |
| ToolBundle expansion | Request metadata and expansion event move to the next cache epoch | `tests/test_runtime.py` |
| After-turn learning reflection | Reflection request metadata includes stage, capabilities, and cache plan | `tests/test_runtime.py` |
| Config capabilities | JSON output redacts API keys and reports capability metadata | `tests/test_cli.py` |
| Provider usage cache tokens | Completion metadata includes normalized cache metrics | `tests/test_providers.py` |

### 5. Good/Base/Bad Cases
- Good: add new provider assumptions in `mnemo/providers/capabilities.py`.
- Good: expose capability metadata to the model and harness, then let the model decide which tools to call.
- Base: model context windows may be unknown for OpenAI-compatible deployments.
- Bad: branching runtime workflows based on provider capability metadata.
- Bad: storing raw tool schemas inside `cache_plan`.

### 6. Tests Required
- Unit tests for provider capability resolution.
- Runtime tests for prompt/request metadata.
- Runtime tests for after-turn learning request metadata.
- CLI tests for capability inspection and secret redaction.
- Provider adapter tests for normalized cache token metadata.
