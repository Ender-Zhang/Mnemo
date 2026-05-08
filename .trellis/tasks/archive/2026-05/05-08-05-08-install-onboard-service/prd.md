# Install Onboard Service

## Goal
Make a fresh Mnemo install usable without manually starting web services or running separate channel commands.

## Requirements
- Add a top-level `mnemo onboard` flow that can configure runtime API provider settings and optionally bind Feishu/Lark through the existing QR scan-to-create implementation.
- Keep provider secrets out of normal settings and stdout; if a pasted key is needed for service startup, persist it only in a state-local 0600 service environment file.
- Add a `mnemo service` surface to install/start/stop/restart/status the local web service, using launchd on macOS, systemd user services on Linux, and a detached fallback when neither manager is usable.
- Update `scripts/install.sh` to run onboard and start the service by default, with non-interactive fallback and skip flags.
- Acknowledge Hermes Agent and OpenClaw as implementation references while keeping Mnemo-specific code.
- Add focused tests for CLI parsing, non-interactive onboard, service plan/env behavior, and installer documentation.

## Non-goals
- Do not add a new external process manager dependency.
- Do not store raw API keys in Web settings or config inspection output.
- Do not replace the existing Feishu QR implementation.
