# Telegram End-to-End Demo

Use a dedicated BotFather bot in a dedicated DM or private group only. Default
Privacy Mode supports DM, mentions, and replies; do not disable it unless later
testing ambient behavior. January groups remain `mention_only` by default.

```bash
./scripts/january-demo.sh init
chmod 600 .env.demo
# Edit .env.demo locally: token, one provider/model, and dedicated chat IDs.
./scripts/january-demo.sh doctor
./scripts/january-demo.sh bootstrap --confirm-live-telegram
./scripts/january-demo.sh up --confirm-live-demo
```

Set `JANUARY_DEMO_LIVE_ENABLED=true` only after reviewing the dedicated bot and
allowlist. `up` starts only the demo's PostgreSQL/Redis containers and separate
API, poller, dispatcher, conversation, planning, and outbound processes. Send a
DM, or an explicit group mention/reply, then run `./scripts/january-demo.sh
status`, `inspect`, or `logs`. Stop local processes without deleting volumes:

```bash
./scripts/january-demo.sh down
```

Never use a production bot/chat. A Telegram webhook blocks polling; January
never removes it automatically. The only Telegram identity request is the
explicit `bootstrap --confirm-live-telegram` command.

Provider authentication/rate-limit failures remain durable planning failures.
Missing sticker mappings skip stickers. `delivery_unknown` is never resent
automatically; use the explicit recovery command only after accepting a
possible duplicate.

With `JANUARY_RATE_LIMIT_ENABLED=true`, Redis failure blocks provider and
Telegram I/O and requeues durable work. The safety policy rechecks current
mention/teasing opt-outs and privacy deletion immediately before external I/O;
the demo never treats its synthetic validation as semantic moderation proof.

Synthetic proof is safe to run in CI or locally and does not require a token,
provider, or public network:

```bash
JANUARY_DB_HOST_PORT=5433 JANUARY_REDIS_HOST_PORT=6380 ./scripts/validate-demo.sh
```

## Live Procedure

Set both `JANUARY_DEMO_LIVE_ENABLED=true` and
`JANUARY_DEMO_LIVE_TELEGRAM_VERIFICATION_ENABLED=true` only in the protected
local demo file. Configure a dedicated bot, a supported provider/model and key
where required; never add a production chat to the allowlist.

Before the poller starts, send a short message to the dedicated bot and run:

```bash
./scripts/january-demo.sh discover-chats --confirm-live-telegram
# Copy the intended chat ID into .env.demo; discovery never changes it.
./scripts/january-demo.sh doctor --confirm-live-telegram --confirm-live-provider
./scripts/january-demo.sh bootstrap --confirm-live-telegram
./scripts/january-demo.sh up --confirm-live-demo
```

Discovery reads safe chat metadata without writing January's polling cursor or
deleting Telegram updates, so the actual poller may receive the update again.
Live doctor checks call `getMe`, `getWebhookInfo`, and, with the provider flag,
one synthetic structured request. They do not send Telegram messages. An active
webhook blocks polling and January never removes it automatically.

For a group, use an explicit `@bot_username` mention or reply to a January
message; ordinary messages remain in `mention_only`. Inspect safe state with
`status`, `inspect`, and `logs`. Expected durable stages are one incoming update,
conversation record, planning job/attempt, response plan, ordered outbound
action/delivery attempt, and outgoing Message. Restarting must not send again.

On failure inspect active-webhook, Privacy Mode, provider auth/rate-limit/
timeout, bot membership, sticker mapping, and PostgreSQL/Redis state. Stop with
`./scripts/january-demo.sh down`; it preserves volumes and delivery records.

## Personality Configuration Acceptance

This is an operator-owned live procedure, not CI evidence. With the guarded
demo already running, locate the internal conversation UUID with `inspect` and
use the local-only configuration CLI. The CLI does not contact Telegram or the
provider.

```bash
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json \
  show-effective --conversation-id CONVERSATION_UUID
# Send one eligible message, then inspect its planning job snapshot IDs.
PYTHONPATH=backend uv run python -m app.runtime.demo_inspector \
  --conversation-id CONVERSATION_UUID
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json \
  create-profile --assistant-id ASSISTANT_UUID --slug calmer \
  --display-name Calmer --apply
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json \
  create-version --profile-id PROFILE_UUID --humor-level 0.2 \
  --teasing-level 0 --apply
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json set \
  --conversation-id CONVERSATION_UUID --profile-version-id PROFILE_VERSION_UUID \
  --expected-revision REVISION --apply
```

Send a comparable eligible message and inspect it: its profile version and
configuration revision IDs must differ from the prior job. Inspect another
conversation to confirm its current revision is unchanged. Disable stickers
with `set --stickers-enabled false`, verify no later sticker action is sent,
then pause with `pause --apply`; no new job, model call, or reply should occur.
Resume only with an explicit non-paused mode, such as `resume --response-mode
mention_only --apply`, and stop the demo safely. Tone is probabilistic; accept
the procedure based on persisted IDs and policy effects, not subjective output.
