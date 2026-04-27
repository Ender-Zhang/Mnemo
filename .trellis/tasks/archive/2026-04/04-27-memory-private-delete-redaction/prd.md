# Private Delete Memory Redaction

## Goal
Finish the first selective-forgetting slice for memory: when a user asks to delete a memory, Mnemo must remove the original memory text from active storage while retaining only a compact tombstone/hash so the fact is not automatically recreated.

## Requirements
- Add a bounded `MemoryEngine.private_delete_memory()` path for candidates and stable pages.
- Redact memory page title/content and candidate claim/evidence in storage; do not keep the deleted text in tombstone summary, metadata, tool evidence, CLI output, or health cards.
- If a page came from a source candidate, redact the source candidate as part of the same private-delete operation.
- Preserve a durable tombstone with `target_hash`, reason, minimal summary, and do-not-resurrect rule.
- Make L4 session tombstone suppression respect private-delete tombstones using source run provenance without storing raw deleted text.
- Expose the capability through CLI and provider-native tool specs as a normal write tool, not a fixed workflow.
- Update design, checklist, and backend specs.

## Acceptance Criteria
- [x] Private-deleting a page redacts the page and source candidate, writes compact tombstones, removes active recall, and keeps raw deleted text out of health/tombstone outputs.
- [x] Private-deleting a candidate redacts claim/evidence, writes a compact tombstone, and suppresses source-run session snippets by default.
- [x] `mnemo memory forget ... --json` and plain output work and normalize missing ids.
- [x] `memory_private_delete` works through ToolHarness and returns compact evidence.
- [x] Focused memory/CLI/tool tests and full package gates pass.

## Technical Notes
- Reuse existing tombstone, status, and compact output patterns.
- Avoid a schema migration unless existing columns cannot support redaction.
- Keep private-delete conservative: no background workflow and no broad database scan.
