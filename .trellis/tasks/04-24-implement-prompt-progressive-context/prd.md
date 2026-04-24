# Implement Prompt Progressive Context

## Goal

Expose memory and skills as compact prompt indexes so the model can decide when to call native tools for details, without rule-based routing or full-context stuffing.

## Scope

- Add compact memory cards sourced from the memory engine.
- Add compact skill cards sourced from the skill service.
- Extend prompt assembly with optional memory and skill index blocks.
- Keep the cache-friendly stable prefix intact when no dynamic context exists.
- Pass cards into the provider runtime.
- Add tests for block ordering, metadata, and provider input.

## Non-Goals

- No embeddings, LLM compression, or workflow router.
- No automatic filesystem skill scan during prompt assembly.
- No full memory page or full skill body injection.
