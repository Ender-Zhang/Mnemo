# Feishu Service Sidecar

## Goal
A user who completes Feishu/Lark QR binding should receive replies without manually running a second channel command.

## Requirements
- Diagnose current production-like state when Feishu is configured but no listener process exists.
- Make `mnemo service install/start/restart` launch the web UI and a Feishu/Lark channel sidecar when saved Feishu config has `connection=websocket`.
- Keep service output/log files separate enough to debug web vs Feishu failures.
- Avoid leaking Feishu app secrets or provider API keys in CLI output, service metadata, or logs added by Mnemo.
- Ensure stop/restart handles both managed child processes in detached mode.
- Add tests proving service launchers include Feishu sidecar only when saved config is websocket-enabled.
- Restart `mnemo-web` / mem.day.qzz.io and also start the Feishu listener so the bound bot responds.

## Acceptance Criteria
- `mnemo channels feishu status --state-dir .mnemo` shows configured websocket and `ps` shows a Feishu listener after service start or deployment restart.
- Unit tests pass.
- `https://mem.day.qzz.io/api/health` remains OK.
- Git commit and push completed.
