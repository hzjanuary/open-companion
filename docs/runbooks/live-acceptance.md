# Telegram Live Acceptance (SPEC-022)

Operator-owned staging and production acceptance for the dedicated Telegram bot
defined in `docs/product/specs/SPEC-022-telegram-production-integration-and-live-acceptance.md`.
Synthetic tests remain required but do not count as evidence that Telegram
webhook delivery, identity, permissions, network behavior, and production
recovery work with the intended bot. A successful `getMe` check alone is never
production authorization.

Every command below contacts Telegram and therefore requires the explicit
`--confirm-live-telegram` flag. No command registers, replaces, or deletes a
webhook as a side effect of API startup. Outputs contain redacted metadata only;
the bot token and webhook secret are never printed, logged, or written to
evidence artifacts.

## SPEC-042 release authorization and bounded scope

Follow [production promotion](production-promotion.md) for fresh release
acceptance. Approval is separate from CLI confirmation flags. Without explicit
scope, dedicated approved bot/connection/chat and HTTPS/TLS/webhook secret,
do not run live commands. A credential, `getMe`, historical fake-adapter proof
or green Quality never grants production or live authority.

For one SPEC-042 smoke run, at most **10 outbound Telegram API operations**
total, or a stricter approved bound. Include identity/webhook/evidence calls,
typing (up to five per planning execution), reaction, send/edit/voice, retries
and command acknowledgement. Reserve worst-case automatic calls and final
evidence calls before each stimulus. If remaining capacity cannot cover them,
stop and report the unexecuted flow; never weaken presence/safety/rate/retry
policy to fit the smoke. Observe actual API calls, not just user-message count.
One response does not prove unexecuted command/ordering/voice flows.

Source-export module commands need `PYTHONPATH=backend`; the runtime image
already supplies it. Do not use a developer `.env` for live release commands.
Legacy raw `verify-model-provider.sh --live` and
`verify-telegram-delivery.sh --live` helpers are not SPEC-042 acceptance: they
do not prove persisted provider admission/accounting or durable delivery.
Run the authorized governed worker path instead; no raw call bypass.

Only harmless synthetic non-sensitive text in the approved chat. No unrelated
users, harmful content, forced live failures or destructive privacy deletion.
Historical failure drills below require separately scoped staging approval,
not default promotion smoke.

Provider-backed turns require separate billing/account approval, approved
model/routes/data eligibility, pricing/hard budget/rate/concurrency and finite
call/spend bounds. Without it use synthetic/mock proof and mark live response
proof pending. TTS needs both scopes, enabled capability and approved chat:
one approved generation, governed usage/artifact/delivery/retention metadata,
then existing governed cleanup eligibility. Never repeat ambiguous possible-I/O
or regenerate audio because delivery failed.

Verify durable ingress/idempotency, current scope, response/reply, safe ordering
if bounded, deterministic acknowledgement, outbound terminal delivery/mapping
and no duplicate/foreign scope. Record operation/type/time, opaque alias,
status and latency class only. Existing collector/inspector may include scoped
IDs: keep originals restricted and sanitize before release docs. Its content
guard is not identity anonymization. No real chat/user IDs, text, prompt,
provider body, memory/knowledge/audio; use role/team and test-group aliases.

Cleanup preserves durable review evidence and ambiguity quarantine. Remove only
approved test resources, make synthetic voice eligible for retention/purge;
real erasure, backup deletion, restore, webhook changes and secret rotation need
separate authority. No production/live authorization was supplied for this goal.

## Prerequisites

Before any live acceptance run the operating owner must verify, per FR-01:

- the intended environment and `JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID`;
- the approved bot identity and `JANUARY_TELEGRAM_BOT_TOKEN` reference;
- exactly one delivery mode (`webhook` or `polling`);
- the HTTPS public base URL and webhook secret reference for webhook mode;
- the dedicated test group, approved bot membership and Privacy Mode;
- the owning operator, incident contact, and rollback authority.

Staging and production must use separate bots, tokens, secrets, domains,
databases, queues, groups, and telemetry destinations. Missing, malformed,
ambiguous, or inconsistent configuration fails closed.

## 1. Connection readiness and identity

Reconcile the approved connection record (the operator bootstrap persists it),
then verify the configured bot identity against that record and inspect the
current Telegram webhook state:

```bash
# Dedicated demo/staging only; production demo bootstrap is forbidden:
./scripts/january-demo.sh bootstrap --confirm-live-telegram
uv run python -m app.runtime.telegram_connection_operations verify \
  --confirm-live-telegram --json
```

The `verify` operation calls `getMe`, compares the returned bot ID with the
approved connection record, inspects `getWebhookInfo`, and evaluates mode
exclusivity. It exits non-zero when identity, configuration, or mode state is
inconsistent. An identity mismatch, revoked token, authentication error, or
unverifiable response blocks acceptance.

## 2. Webhook lifecycle

Webhook lifecycle is an explicit operator/deployment operation:

```bash
uv run python -m app.runtime.telegram_connection_operations webhook-inspect \
  --confirm-live-telegram --json
uv run python -m app.runtime.telegram_connection_operations webhook-register \
  --confirm-live-telegram --json
```

`webhook-register` re-verifies identity, inspects current state, registers the
approved HTTPS URL with the configured secret and allowed update set, then reads
`getWebhookInfo` again and fails closed unless Telegram reports the expected URL
and update set. Activation time and operator are recorded in the output and in
the evidence bundle.

The legacy helpers remain available: `./scripts/telegram-webhook.sh inspect`,
`register`, and `remove`. Dropping pending updates is destructive and requires
separate explicit authority; never use it for ordinary cutover. Failed
registration or verification leaves the connection unavailable
and never silently falls back to polling.

## 3. Polling exclusivity and mode transitions

For each connection exactly one of `disabled`, `webhook`, or `polling` is
active. The poller refuses to poll while Telegram reports a webhook and never
deletes a webhook automatically.

A mode change requires explicit drain/stop of the old mode, then verification of
Telegram state, then activation of the new mode. Use the gate before and after:

```bash
uv run python -m app.runtime.telegram_connection_operations mode-verify \
  --confirm-live-telegram --json
```

`mode-verify` exits non-zero when Telegram state conflicts with the configured
mode (for example a webhook still active while the connection is in `polling`).
Its evidence shows that no second ingress source was active during the
transition.

## 4. Live staging acceptance

With the dedicated staging bot active and the staging workers running:

1. Send one addressed message in the staging group and verify the durable path:
   ingress record, conversation record, planning job, response plan, ordered
   outbound action, and delivery attempt. Read the metadata-only trace with:

   ```bash
   uv run python -m app.runtime.demo_inspector --telegram-update-id UPDATE_ID --json
   ```

2. Exercise one supported membership/configuration event (`my_chat_member` or
   `chat_member`) and verify its durable outcome.

3. Replay the same update and verify one canonical ingress record and no
   duplicate terminal response effect.

An addressed message is accepted only when Telegram delivery is confirmed or
classified according to the existing delivery-certainty contract. Timeout or
ambiguous post-send outcomes are `delivery_unknown` or quarantine, never counted
as duplicate-safe success.

## 5. Failure and recovery drills

Where the test account permits, exercise or observe controlled failure so each
maps to a stable internal category and its documented recovery state:

- duplicate replay, worker restart, and lease/consumer-group reclaim;
- DNS/connectivity failure, timeout, malformed response, authentication failure,
  forbidden chat/action, invalid request, conflict, and server-side failure;
- Telegram `429` rate limits honoring retry-after within the existing bounded
  retry policy (no busy loop, rate limits never counted as delivered);
- ambiguous post-send outcome preserved as `delivery_unknown` or quarantine.

Invalid requests, authentication failures, unsupported updates, policy refusals,
and confirmed Telegram rejections are never retried as transient network
failures. Dependency loss must produce the documented readiness states.

## 6. Operational evidence

Every live run produces a reviewable, content-safe evidence bundle:

```bash
uv run python -m app.runtime.acceptance_evidence collect \
  --confirm-live-telegram \
  --operator OPERATOR --incident-contact CONTACT --rollback-authority AUTHORITY \
  --test-group STAGING_GROUP --confirm-cleanup --out evidence.json
```

The bundle records environment, connection, redacted bot identity, webhook or
polling state, mode exclusivity, timestamps, run and correlation IDs, result
classification, health/readiness responses, worker lifecycle, duplicate/retry
outcomes, owners, and cleanup confirmation. It contains no message content,
credentials, tokens, prompts, memories, vectors, or provider bodies; the
content-safety guard runs on every bundle before it is emitted. Use
`--no-durable-state` when PostgreSQL is not reachable, and `--app-base-url` to
point `/health` and `/ready` fetches at the running service.

## 7. Production cutover

Production cutover is accepted only when all SPEC-022 criteria pass for the
production bot, domain, credentials, group, and operating owner, and the Product
Owner and operating owner approve the reviewed evidence bundle. A successful
`getMe` check alone is never production authorization. Record the activation
owner, time, configuration, and rollback point in the cutover evidence.

## 8. Rollback

To reverse webhook mode, delete the webhook explicitly and verify Telegram
state, or activate polling only after the webhook is confirmed removed:

```bash
uv run python -m app.runtime.telegram_connection_operations webhook-delete \
  --confirm-live-telegram --confirm-delete-webhook --json
uv run python -m app.runtime.telegram_connection_operations mode-verify \
  --confirm-live-telegram --json
```

Roll back application code or configuration when possible; database downgrade
remains an exceptional, explicitly scoped action governed by SPEC-020.

## 9. Cleanup

Remove staging test resources or explicitly retain them by owner approval.
Confirm no pending updates remain on the staging bot unless retention is
approved, and stop the staging stack without deleting durable records needed for
review:

```bash
docker compose down
```
