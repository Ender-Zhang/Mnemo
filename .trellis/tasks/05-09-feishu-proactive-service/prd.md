# Feishu Proactive Service

## Goal

Implement Mnemo proactive service so scheduled proactive work can reach the user in Feishu while respecting quiet-hours, delivery frequency, and explicit user/channel constraints.

## Requirements

- Run due proactive schedule items automatically from the web service background loop.
- Deliver eligible proactive messages to Feishu without requiring an inbound user message.
- Keep Dream maintenance automatic and provider-backed.
- Avoid disturbing users through quiet-hours, rate limits, channel availability checks, and conservative delivery defaults.
- Persist delivery decisions and failures compactly for status inspection and retries.
- Keep Feishu credentials redacted and state-local.
- Route model work through existing runtime/provider services, not a parallel agent loop.

## Acceptance Criteria

- [x] Web service starts a background proactive scheduler alongside auto Dream.
- [x] Due watch/cron items are processed and drained automatically.
- [x] Eligible proactive queue items are sent to Feishu chat ids from saved channel metadata/config.
- [x] Quiet-hours and per-chat throttling defer rather than drop proactive work.
- [x] Delivery failures are recorded without leaking secrets.
- [x] Runtime status exposes compact proactive service state.
- [x] Tests cover delivery, quiet-hours deferral, missing Feishu binding, and queue draining.

## Technical Notes

- Reuse `ScheduleService`, `DaemonRunner`, `FeishuClient`, channel metadata, and existing runtime paths.
- Add a small proactive delivery layer for policy and Feishu outbound dispatch.
- Prefer model/runtime output for proactive content; policy only decides delivery timing.
