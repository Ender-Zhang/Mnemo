# Implement Provider Capability Registry

## Goal
Add a generic provider capability registry so Mnemo can reason about prompt cache strategy, ToolBundle epochs, model context windows, and fallback modes without scattering provider-specific constants through runtime code.

## Requirements
- Define structured provider capabilities for local, OpenAI-compatible, Anthropic, and unknown provider adapters.
- Expose compact capability metadata in `prompt.assembled` and provider request metadata.
- Use capabilities to choose ToolBundle provider adapter versions.
- Add CLI inspection for resolved provider capabilities.
- Extract provider cache token usage into normalized metadata when providers return it.
- Update code-specs and checklist.

## Non-Goals
- Do not implement Anthropic `cache_control` injection or OpenAI prompt cache keys in this task.
- Do not add SDK/MCP or new provider adapters.
