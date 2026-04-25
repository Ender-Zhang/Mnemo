# After-turn learning packet

## Goal
Implement the first runnable version of Mnemo's unified after-turn learning packet so one completed turn can produce 0..N mixed learning candidates through provider-native tool calls.

## Requirements
- Build a compact `learning_packet` from the completed run, assistant response, and compact tool results.
- Persist packet and reflection lifecycle events to RunLedger for replay/debugging.
- In provider runtime, run a bounded after-turn reflection using the same provider-native tool call path.
- Expose only learning candidate tools for reflection: memory, skill, tool, eval case, and discard.
- Let the model decide whether to call 0..N tools; do not implement a memory-first/skill-second workflow.
- Keep packet payloads compact and avoid raw artifact bodies, raw tool schemas, or full transcripts.
- Project skill/tool/eval learning candidates into unified learning chips when they are proposed.
- Local runtime should at least record the packet foundation without attempting deterministic candidate extraction.

## Acceptance
- [x] `ProviderAgentRuntime` can call learning tools after the user-facing answer using a compact packet.
- [x] Reflection tool calls reuse `ToolHarness`, permissions, compact evidence, and provider-native schema handling.
- [x] Existing provider and local runtime tests still pass.
- [x] New tests cover a provider proposing mixed memory/skill/tool/eval candidates from one packet.
- [x] Specs and checklist document the implemented foundation and remaining limits.
