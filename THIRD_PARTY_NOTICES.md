# Third-Party Notices

## Hermes Agent

Mnemo's web tool split between compact `web_search` result metadata and page-oriented `web_fetch` was informed by the MIT-licensed Hermes Agent web tools design from Nous Research:

- Repository: https://github.com/NousResearch/hermes-agent
- Reference file: `tools/web_tools.py`
- License: MIT License, Copyright (c) 2025 Nous Research

Mnemo's implementation is stdlib-only and project-specific; no Hermes source code was copied.

Mnemo's one-click installer, Feishu/Lark scan-to-create onboarding, and Feishu/Lark channel were also informed by Hermes Agent's installation and gateway boundary patterns:

- Reference files: `scripts/install.sh`, `gateway/platforms/feishu.py`
- Patterns referenced: inherited Python environment sanitation, isolated venv command linking, Feishu scan-to-create registration shape, URL verification, optional token/signature checks, callback deduplication, and background message processing.

Mnemo's installer, onboarding flow, and Feishu channel are Mnemo-specific implementations routed through Mnemo runtime services; no Hermes source code was copied.
