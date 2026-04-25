# Validate OpenAI Compatible Provider Chain

## Goal
Run the real OpenAI-compatible provider chain against the supplied GPT-5.4 endpoint and verify Mnemo can list models, smoke chat, execute a provider-backed turn, persist events, and replay the run.

## Requirements
- Use the supplied endpoint only through temporary environment variables.
- Do not persist or print the API key.
- Validate `/v1/models` and `/v1/chat/completions` directly.
- Validate `mnemo config smoke` with `--provider openai-compatible`.
- Validate `mnemo run --provider openai-compatible --json` persists conversation, mission, run, prompt metadata, and replayable events.
- If failures are caused by Mnemo code, fix them in this task and add focused tests.

## Acceptance Criteria
- [x] Direct models endpoint returns a usable model list including or compatible with `gpt-5.4`.
- [x] Direct streaming chat completion returns text for `gpt-5.4`.
- [x] Direct non-streaming chat behavior is recorded for `gpt-5.4`.
- [x] `mnemo config smoke --stream` succeeds and redacts credentials.
- [x] Provider-backed streaming `mnemo run` succeeds and returns replayable events.
- [x] `mnemo prompt inspect`, `mnemo events`, and `mnemo replay` work for the provider-backed run.
- [x] Any code/spec/checklist changes are tested, committed, and pushed.

## Validation Notes
- `https://cpa.spirit.cc.cd/v1/models` returned 20 model ids including `gpt-5.4`.
- Non-streaming `gpt-5.4` chat returned HTML despite HTTP 200 and `application/json`; streaming `gpt-5.4` chat returned valid SSE.
- `gpt-5.4-mini` non-streaming chat worked, confirming the endpoint and credentials are valid.

## Technical Notes
- The intended provider config is OpenAI-compatible with model `gpt-5.4`.
- Base URL probing may need to normalize whether the endpoint expects `/v1`.
