# Third-Party Notices

## Hermes Agent

Mnemo's web tool split between compact `web_search` result metadata and page-oriented `web_fetch` was informed by the MIT-licensed Hermes Agent web tools design from Nous Research:

- Repository: https://github.com/NousResearch/hermes-agent
- Reference file: `tools/web_tools.py`
- License: MIT License, Copyright (c) 2025 Nous Research

Mnemo's implementation is stdlib-only and project-specific; no Hermes source code was copied.

Mnemo's one-click installer, Feishu/Lark scan-to-create onboarding, and Feishu/Lark channel were also informed by Hermes Agent's installation and gateway boundary patterns:

- Reference files: `scripts/install.sh`, `hermes_cli/setup.py`, `hermes_cli/gateway.py`, `gateway/platforms/feishu.py`
- Patterns referenced: inherited Python environment sanitation, isolated venv command linking, setup wizard separation of non-secret config from service-only environment secrets, persistent gateway/service lifecycle, Feishu scan-to-create registration shape, URL verification, optional token/signature checks, callback deduplication, and background message processing.

Mnemo's installer, onboarding flow, and Feishu channel are Mnemo-specific implementations routed through Mnemo runtime services; no Hermes source code was copied.

## OpenClaw

Mnemo's install/onboard service shape also acknowledges OpenClaw's local gateway pattern: a long-running localhost service with channel sidecars and runtime health visibility.

- Reference: https://docs.openclaw.ai/concepts/agent-workspace
- Reference: https://docs.openclaw.ai/concepts/system-prompt

Mnemo keeps its own CLI, service files, settings schema, and Feishu implementation; no OpenClaw source code was copied.
