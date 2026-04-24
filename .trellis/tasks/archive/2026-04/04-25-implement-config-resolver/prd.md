# Implement Config Resolver

## Goal

Centralize Mnemo's runtime configuration resolution so CLI, Web, and future daemon code share the same provider and state settings without duplicating env parsing.

## Scope

- Support optional JSON config file.
- Apply precedence: CLI overrides, environment, config file, defaults.
- Preserve existing env names.
- Resolve provider API keys from env only; do not expose secrets in inspect output.
- Add `mnemo config inspect`.
- Refactor CLI/Web provider setup to use the resolver.
- Add unit and CLI tests.

## Non-Goals

- No config write command.
- No secret persistence.
- No multi-profile manager.
