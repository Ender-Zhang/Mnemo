# Implement Tool Bundle Epochs

## Goal
Add a stable, versioned ToolBundle layer between `ToolRegistry` and provider-native tool calls, so prompt metadata and runtime traces can track schema cost, cache identity, and lazy schema expansion without embedding raw schemas in prompt text.

## Requirements
- Compile deterministic `ToolBundle` objects from registry specs with stable bundle ids and compact metadata.
- Preserve default `full` runtime behavior.
- Add smaller `minimal` and `capsule` tool profiles aligned with prompt modes.
- Add read-only `tool_search` and `tool_expand_schema` tools for compact discovery and provider-loop schema expansion.
- Record bundle metadata in `prompt.assembled` and provider request metadata.
- If `tool_expand_schema` succeeds in a provider loop, create a new bundle epoch for the next model round and record the cache bust reason.

## Non-Goals
- Do not implement MCP, SDK, or provider cache-control headers in this task.
- Do not add workflow routing; the model still decides whether to search or expand tools through provider-native tool calls.
