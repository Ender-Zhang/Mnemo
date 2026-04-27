# External Command Runtime Adapter

## Goal
Implement the first actual `RuntimeAdapter` execution path by running a bounded external command with a minimal-disclosure context capsule and accepting only structured proposal output.

## Requirements
- Build a context capsule before invoking the external runtime.
- Execute an explicit argv command with the capsule JSON on stdin.
- Keep execution bounded by timeout and stdout/stderr byte caps.
- Accept only structured proposal fields from the external return contract.
- Record run, capsule, command, proposed result, ignored fields, and boundary violations in RunLedger.
- Do not let the external runtime directly mutate memory, skills, tools, schedules, or artifacts.
- Expose the adapter through SDK, CLI, MCP, and the external-harness eval.

## Acceptance Criteria
- [ ] `CommandRuntimeAdapter` returns `external_runtime_result` payloads with run ids and compact proposals.
- [ ] CLI exposes `mnemo api external-run TASK... --command-json '[...]' --json`.
- [ ] SDK/API schema exposes `external_run`.
- [ ] MCP exposes `mnemo_external_run`.
- [ ] External-harness suite verifies fresh capsule execution and ignores unsupported output fields.
- [ ] Tests cover success, timeout/failure normalization, CLI, SDK, MCP, and harness behavior.
- [ ] Checklist/spec/docs describe the new foundation and remaining limitations.

## Technical Notes
- This is a command adapter foundation, not a full OpenClaw/Codex/ACP protocol implementation.
- Command execution is explicit; no shell string execution.
- JSON output is preferred; plain text stdout becomes a summary proposal.
