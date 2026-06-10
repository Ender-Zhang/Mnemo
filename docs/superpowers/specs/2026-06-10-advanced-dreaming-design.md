# Advanced Dreaming Design

Date: 2026-06-10

## Goal

Upgrade Dreaming from candidate review plus light maintenance into a semi-automatic memory organizer.

The system should still be safe by default:

- Low-risk actions may run automatically.
- High-risk stable-memory edits become pending proposals.
- Every proposal is persisted, reviewable, and traceable.

## User Choice

The selected operating mode is **semi-auto**.

WebUI should expose a new switch:

- `高级 Dreaming`
- Off: keep current Dream behavior.
- On: send `advanced_dreaming: true` and `execution_policy: "semi_auto"` to `dream-run`.

This is separate from the existing `使用模型审核` switch. A Dream run only asks the model for actions when `use_provider` is true.

## Normal Dreaming

Normal Dreaming keeps the current behavior:

- Promote candidates.
- Reject candidates.
- Tombstone memory when explicitly requested by the model.
- Decay stale pages.
- Compile L1 snapshot.
- Save a dream report.

## Advanced Dreaming

Advanced Dreaming extends the model plan with reorganization tools:

- `memory_link_pages`: add a non-destructive link between stable memory pages.
- `memory_rewrite_page`: propose a new title/content for one stable memory page.
- `memory_merge_pages`: propose merging multiple stable pages into a target page.
- `memory_split_page`: propose splitting one stable page into multiple new pages.
- `memory_reconcile_conflict`: propose replacing or clarifying conflicting stable facts.

## Semi-Auto Policy

Automatically apply:

- Existing candidate review actions.
- Existing decay actions.
- Snapshot compilation.
- `memory_link_pages`, because links are additive and reversible.

Persist as pending proposals:

- `memory_rewrite_page`
- `memory_merge_pages`
- `memory_split_page`
- `memory_reconcile_conflict`

Do not automatically apply:

- Stable page rewrites.
- Stable page merges.
- Stable page splits.
- Conflict replacement.
- Hard deletion.

## Proposal Storage

Add a persistent `dream_proposals` table. A proposal stores:

- proposal id
- report id
- tool name
- title
- rationale
- risk level
- status: pending, applied, rejected
- action JSON
- before JSON
- after JSON
- created time
- decided time

The table is initialized with SQLite `CREATE TABLE IF NOT EXISTS`, consistent with the existing storage style.

## API

Extend:

- `dream-run`
  - `advanced_dreaming: bool`
  - `execution_policy: "semi_auto"` for the first version

Add:

- `dream-proposals`
  - list pending/applied/rejected proposals
- `apply-dream-proposal`
  - apply one pending proposal
- `reject-dream-proposal`
  - reject one pending proposal with a reason

## WebUI

Settings:

- Add a local `高级 Dreaming` switch next to `使用模型审核`.
- Persist it in browser `localStorage`.

Run Dream:

- Send `advanced_dreaming` and `execution_policy`.
- Mention proposal counts in the success message.

Maintenance page:

- Default mode shows a compact proposal count.
- Advanced mode shows a proposal panel with pending proposals and actions.

Proposal panel:

- Show tool, title, rationale, risk, status.
- Show before/after JSON in advanced mode.
- Allow Apply and Reject for pending proposals.

## First-Version Boundaries

This version does not attempt fully autonomous memory rewriting.

It can apply confirmed high-risk proposals, but only through explicit WebUI/API action. The model cannot silently rewrite stable memories.

The first apply implementation supports:

- `memory_link_pages`
- `memory_rewrite_page`
- `memory_merge_pages`
- `memory_split_page`
- `memory_reconcile_conflict`

All applied proposals update the proposal status and leave evidence in the proposal record and Dream report.
