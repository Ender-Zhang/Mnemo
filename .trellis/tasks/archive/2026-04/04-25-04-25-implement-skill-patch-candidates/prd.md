# Implement Skill Patch Candidates

## Goal

Allow the model to propose a bounded patch to an existing skill as a new draft skill candidate, without directly mutating active skill files or bypassing review/eval/promotion gates.

## Requirements

- Add a skill patch service API that applies exact UTF-8 text replacements to an existing skill body in memory.
- Store the patched result as a draft skill candidate with compact provenance.
- Expose the capability through the learning tool set so provider-native tool calling can use it.
- Reject missing skills, missing replacement text, and ambiguous replacements unless `replace_all=true`.
- Keep prompt/tool results compact and omit full skill bodies from evidence.
- Update backend skill-evolution contracts and implementation checklist.

## Acceptance Criteria

- [x] `SkillService.patch_candidate(...)` creates a draft patched candidate from an existing skill.
- [x] `skill_patch_candidate` appears in tool specs and executes through `ToolHarness`.
- [x] Missing skill and ambiguous replacement cases are rejected deterministically.
- [x] Compact summaries/evidence do not include full skill bodies.
- [x] Focused and full unit tests pass.
- [x] Trellis task validation passes.
- [x] Changes are committed locally.

## Technical Notes

- This is a capability, not a workflow router. The model decides whether to call it and what replacements to propose.
- The patched candidate remains draft until eval/review/promotion explicitly accepts it.
- Use existing StateStore skill rows rather than adding a new storage table.
