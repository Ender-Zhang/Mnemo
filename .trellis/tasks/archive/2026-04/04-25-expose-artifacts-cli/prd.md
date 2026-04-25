# Expose Artifacts CLI

## Goal
Expose stored mission artifacts through a small read-only CLI so users can inspect generated task outputs outside the web UI.

## Requirements
- Add `mnemo artifacts list` with optional `--mission-id`, `--run-id`, `--limit`, and `--json`.
- Add `mnemo artifacts read <artifact_id>` with optional `--json`.
- Keep list output compact and omit full artifact bodies.
- Normalize unknown artifact ids through `MnemoError` so CLI output has no traceback.
- Reuse `StateStore` for persistence access and avoid duplicating SQL in the CLI layer.

## Acceptance Criteria
- [x] CLI can list stored artifact metadata from the local state directory.
- [x] CLI can filter artifact metadata by mission id and run id.
- [x] CLI can read one stored artifact body by id.
- [x] Missing artifact reads exit non-zero with `mnemo: artifact not found: <id>`.
- [x] Storage, CLI, and docs/spec contracts are updated.

## Validation
- `python3.13 -m unittest tests.test_storage.StateStoreTests.test_artifact_round_trip_by_id`
- `python3.13 -m unittest tests.test_cli.CliTests.test_artifacts_commands_list_and_read_stored_artifacts`
- `python3.13 -m unittest tests.test_cli`
- `python3.13 -m unittest tests.test_storage`
- `python3.13 -m unittest discover -s tests`
- `python3.13 -m mnemo harness smoke`

## Technical Notes
- This is a read-only observability feature; no schema migration should be required.
- Artifact bodies must remain explicit lookup data, not duplicated in list/event payloads.
