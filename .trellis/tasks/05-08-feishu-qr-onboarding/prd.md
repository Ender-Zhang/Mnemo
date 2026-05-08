# Feishu QR Onboarding

## Goal
Support Feishu/Lark scan-to-create onboarding so a user can create a personal Feishu bot app from Mnemo without manually visiting the developer console.

## Requirements
- Add a model-independent Feishu/Lark QR registration flow based on the app registration device flow.
- Provide a CLI onboarding command that initializes registration, prints a scan URL, polls for completion, probes bot metadata, and saves the resulting channel config locally with strict file permissions.
- Expose a compact Web onboarding API so the settings page can start and poll the same flow.
- Show Feishu connection status and onboarding controls in the existing settings page.
- Keep the existing webhook channel path working; onboarding only supplies credentials/config.
- Do not expose `app_secret` in Web responses, logs, help text, or settings payloads.
- Keep the Hermes/OpenClaw reference acknowledged; do not copy their source code.

## Acceptance Criteria
- [ ] `mnemo channels feishu onboard` supports QR scan-to-create and reports a masked saved config.
- [ ] Web settings can start Feishu onboarding and poll until configured.
- [ ] `/api/settings` includes compact Feishu status without secrets.
- [ ] `mnemo channels feishu serve` can load saved onboarding config when env/flags are not supplied.
- [ ] Unit tests cover registration init/begin/poll, config persistence, CLI help/validation, Web API status, and asset hooks.
- [ ] README/spec/third-party notices are updated.

## Technical Notes
- Data flow: Feishu accounts registration endpoint -> Mnemo onboarding service -> state-local config -> Feishu channel config -> existing runtime.
- Persisted channel config must be mode `0600`, because scan-to-create returns `app_secret` and automatic serve needs it.
- Web payloads may report `configured`, `domain`, `app_id`, `bot_name`, `bot_open_id`, `owner_open_id`, and `webhook_path`, but never `app_secret`.
