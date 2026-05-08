# One-Click Install And Feishu Channel

## Goal
Add a practical install path and a Feishu/Lark webhook channel so a user can install Mnemo from one shell command and then talk to the same Mnemo runtime from Feishu.

## Requirements
- Provide a `scripts/install.sh` one-click installer for macOS/Linux that installs Mnemo into a venv, links the `mnemo` command, and avoids inherited Python environment leakage.
- Add a Feishu webhook channel that validates Feishu URL challenges, optional verification tokens, optional signatures, deduplicates message callbacks, runs messages through the configured Mnemo runtime, and sends compact text replies back to the Feishu chat.
- Keep Feishu credentials in environment variables or explicit CLI args only; never persist or print app secrets.
- Reuse existing Mnemo runtime/provider services instead of creating a parallel agent loop.
- Document Hermes Agent as the implementation reference source.

## Acceptance Criteria
- `mnemo channels feishu serve --help` documents required options and environment variables.
- Feishu URL verification returns `{ "challenge": ... }`.
- Invalid verification tokens or signatures return compact `401` responses.
- Duplicate event/message callbacks are acknowledged without running another Mnemo turn.
- A valid Feishu text message is processed in the background and sends a reply through Feishu's message API.
- Install script includes `--help`, `--dir`, `--state-dir`, `--repo`, `--branch`, and `--skip-setup`.
- Source tests and package smoke remain green.

## Technical Notes
- Reference reviewed: `NousResearch/hermes-agent` `scripts/install.sh` and `gateway/platforms/feishu.py`.
- This first Mnemo implementation targets Feishu webhook mode only, because it can be implemented dependency-free with stdlib HTTP and urllib.
- Future WebSocket/long-connection support can wrap the same Feishu service once optional dependencies are introduced.
