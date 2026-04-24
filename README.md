# Mnemo

Mnemo is a personal AI operating system runtime. This repository currently contains the design package and the first runnable backend foundation.

## Quick Start

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install .

mnemo init --state-dir .mnemo
mnemo run "remember: I prefer concise implementation updates" --state-dir .mnemo
```

The first implementation slice is intentionally local and deterministic. It exercises the same provider-safe tool-call envelope that future OpenAI and Anthropic adapters will use.

For local development without reinstalling, run tests with `PYTHONPATH=src python -m unittest discover -s tests`.
