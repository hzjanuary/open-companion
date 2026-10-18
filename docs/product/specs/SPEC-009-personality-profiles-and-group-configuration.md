# SPEC-009 Personality Profiles and Group Configuration

SPEC-009 adds immutable typed personality versions and immutable per-conversation
configuration revisions. Each Assistant receives the `January Default` profile;
each Conversation receives a `mention_only` revision selecting that version.
Planning jobs snapshot both immutable IDs at creation, and planning derives a
deterministic effective personality from the snapshot rather than mutable
runtime configuration.

Profiles permit only structured identity, communication, and behavior fields.
Inside jokes, sensitive teasing, and private-memory disclosure remain disabled;
teasing is capped at 0.4. Conversation revisions can override only documented
communication fields, response mode, and sticker enablement. All changes are
transactional, revisioned, and idempotent.

The schema version is `personality-profile-v1`. Unknown fields, non-finite or
out-of-range frequencies, control characters, unsafe boundaries, and custom
prompt text are rejected. Unset overrides inherit and an explicit null clears
one override; hard safety boundaries always come from the immutable profile.
Planning snapshots are created in the job handoff transaction. The prompt uses
their stable structured effective values rather than operator prompt prose, so
identical snapshots create byte-identical requests. Current pause state is
rechecked before provider I/O and current sticker state before Telegram I/O;
already-delivered history is never reversed, while stale queued sticker work is
skipped.

## Lifecycle And Defaults

`January Default` is a typed, immutable version seeded per Assistant with
language `auto`, self-reference `mình`, short casual replies, moderate humor,
low teasing, bounded emoji/sticker frequency, member names enabled, and
follow-up questions allowed sometimes. Inside jokes, sensitive teasing, and
private-memory disclosure are false; stopping teasing on request is true.
Bootstrap and the CLI reconciliation command reuse existing rows, never mutate
a version, and create missing current conversation revisions. Defaults are
`mention_only`, no overrides, and stickers enabled only when a valid configured
platform mapping exists.

## Operator And Acceptance

The local runtime CLI lists profiles/versions, defaults, effective values, and
history; it creates versions, archives profiles, reconciles defaults, selects a
version, changes mode/stickers/one override, and pauses/resumes explicitly.
Writes require `--apply`, support expected revision concurrency, and accept no
prompt text, raw platform identity authority, credentials, or provider access.
Conversations may be addressed by internal UUID or connection UUID plus chat
ID. See `docs/runbooks/group-configuration.md` and the guarded demo acceptance
procedure in `docs/runbooks/telegram-end-to-end-demo.md`.

Validation uses only project PostgreSQL/Redis and fake adapters. It covers
schema rejection and deterministic merge/prompt behavior, migration lifecycle,
reconciliation, immutable/idempotent revisions, ownership conflicts,
conversation isolation, snapshots, paused work, and stale sticker suppression.
The non-goals remain Telegram administration or preference commands,
free-form personalities, memory, moderation expansion, frontend/Zalo, and all
SPEC-010 behavior.

The operator configuration runtime is the only mutation boundary. Telegram
commands, public mutation APIs, arbitrary prompt text, user preferences, and
SPEC-010 administration behavior remain out of scope. Canonical validation uses
PostgreSQL/Redis and fake adapters only; live provider or Telegram calls are
never required.
