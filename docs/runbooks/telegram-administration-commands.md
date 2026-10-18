# Telegram Administration Commands

Use only a dedicated test bot and a private test group. Start the guarded demo
topology with `./scripts/january-demo.sh up --confirm-live-demo`; it starts the
separate command worker only when `.env.demo` explicitly enables it.

Run `/help` and `/status`. As an ordinary member run `/quiet` and confirm the
reply denies the change. As a current Telegram administrator run `/mode
mention_and_name`, `/quiet`, and `/resume`; inspect the durable command job,
revision, response plan, and normal outbound delivery state. Test `/mentions
off` and `/teasing off` from a member account, then confirm only that account's
preferences change.

These deterministic command mutations do not consume model-generation rate
limit capacity. Their normal outbound acknowledgements still use the delivery
queue and can wait for Redis capacity; the mutation itself remains committed.

SPEC-027 extends the same `/memory` namespace. In a private test chat, verify
`/memory`, `/memory list`, `/memory context add preferred_name Mai`, revisioned
`/memory update` and `/memory delete`, `/memory recall off|on`, and `/memory
clear_mine confirm`. Personal context must be rejected in groups and must never
appear in another participant's list. Existing `/memory reset_group confirm`
still requires fresh Telegram group authorization and clears shared explicit
facts only. See [`personal-context.md`](personal-context.md) for migration,
privacy, and recovery checks.

Never use this runbook to register Telegram command menus, change profile
content, expose tokens, or test in a production group. Command menu management
is deferred; visibility does not grant authorization.

SPEC-028 captions and derived voice/audio transcripts are user content, never
command arguments. Speaking or captioning `/memory` or `/forget_me` does not execute
it: send the existing typed command and confirmation instead. Media cannot
silently create memory/personal context. See [Telegram media](telegram-media.md).

SPEC-029 scheduling commands are private-conversation only. Verify `/timezone`,
`/quiet_hours`, `/remind`, `/reminders`, `/cancel_reminder`, and the separately
consented `/checkins` lifecycle using synthetic or dedicated test accounts. A
reminder does not grant check-in consent; group roles grant no scheduling
authority. See [proactive scheduling](proactive-scheduling.md).

The reply-only `/regenerate`, `/voice`, and `/feedback helpful|unhelpful`
commands use retained local message/response authority rather than group-admin
status or Telegram quoted text. Feedback is provider-free participant-owned
metadata and has no fuzzy target or automatic adaptation. See
[regeneration](telegram-regeneration.md), [voice](telegram-voice-tts.md), and
[conversation feedback](conversation-feedback.md).

Every command resolves its tenant and Assistant from the persisted Telegram
connection. Tenant control-plane membership does not grant Telegram group
authority, and Telegram group authority does not grant tenant administration.
If the tenant, Assistant, or connection becomes inactive after a command job is
claimed, the worker fails closed before a fresh Telegram authorization call.
