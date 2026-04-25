# Implement Memory Write Taint Scanner

## Goal
Add a lightweight memory-write safety layer so candidate memories preserve source taint metadata and obvious prompt-injection attempts from external content cannot be promoted through normal Dream consolidation.

## Requirements
- Route model memory writes and W0 retained notes through one MemoryEngine candidate-write path.
- Scan claim/evidence text for obvious instruction hijacking patterns.
- Track taint sources for user, web, file, tool result, imported skill, MCP, and external runtime evidence.
- Mark suspicious candidate writes as `needs_review:prompt_injection` while preserving compact safety evidence.
- Keep scanner deterministic and dependency-free; do not add a fixed workflow/router.
- Add regression coverage in memory, tools, and memory-safety harness.

## Acceptance Criteria
- [x] Safe user-sourced candidates remain `draft` and include low-risk safety metadata.
- [x] External evidence with prompt-injection markers becomes `needs_review:prompt_injection`.
- [x] Dream consolidation does not promote injected candidates.
- [x] `memory_write_candidate` tool returns compact safety metadata/evidence.
- [x] Memory-safety harness includes a prompt-injection scanner case.
- [x] Relevant backend specs and implementation checklist are updated.
- [x] Targeted and full test suites pass.

## Technical Notes
- This is a scanner/gating foundation, not a privacy layer.
- Taint metadata is stored inside candidate evidence to avoid another schema migration.
- Regex/pattern scanning is a cheap prefilter; future model-led review can use the safety evidence.
