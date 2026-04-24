# Implement Generated Tool Installation

## Goal

Complete the tools self-evolution loop by allowing reviewed generated tool candidates to become active tools without executing arbitrary model-generated code.

## Scope

- Add durable storage for installed generated tools.
- Install only candidates that are already `ready`.
- Support a lightweight `alias` implementation that proxies to an existing registered tool.
- Reject installs that lower the target tool's risk level or reference unknown tools.
- Load active generated tools into the runtime registry so providers can see and call them.
- Expose compact model-facing lifecycle tools for install and uninstall.
- Update specs, tests, and checklist.

## Non-Goals

- No arbitrary Python/JS code generation or dynamic imports.
- No multi-step workflow router.
- No browser/app connector work in this task.

## Acceptance

- [x] Ready alias candidates can be installed as active generated tools.
- [x] Non-ready candidates cannot be installed.
- [x] Generated aliases execute through the existing tool registry and policy gate.
- [x] Install validation rejects unknown target tools and permission downgrades.
- [x] Active generated tools appear in `ToolRegistry.from_store(...)` specs.
- [x] Model-facing install/uninstall tools return compact evidence without raw implementation payloads.
- [x] SQLite migration is idempotent and legacy-safe.
- [x] Full unit suite passes.
- [x] Changes are committed locally.
