# SPEC-008 Operator Bootstrap and End-to-End Demo

SPEC-008 provides an explicit local polling workflow for one dedicated Telegram
test bot and configured LLM provider. Normal startup remains disabled and
no-network. Live operation requires `JANUARY_DEMO_LIVE_ENABLED=true`, polling,
LLM/outbound enablement, a nonempty numeric chat allowlist, and explicit command
confirmation.

Bootstrap verifies `getMe` and transactionally creates or reconciles one
January Assistant and Telegram PlatformConnection without persisting the token.
It reports only safe identity/capability metadata and the resulting connection
UUID. A disallowed chat is durably ignored before conversation, planning, or
outbound state can be created.

`january-demo.sh` owns only the local `.env.demo` template workflow and refuses
to overwrite it. The polling, dispatcher, conversation, planning, and outbound
workers remain separate runtimes. No webhook is registered or removed.

The synthetic validator uses fake adapters and project PostgreSQL/Redis only.
Live testing is manual and uses a dedicated bot/test chat; it is never CI work.
SPEC-008 does not add deployment, RBAC, webhooks/tunnels, admin commands,
frontend, or SPEC-009 personality configuration.

## Operator Contract

The committed `.env.demo.example` is secret-free; `init` creates ignored
`.env.demo` only when absent and uses restrictive permissions. Doctor performs
configuration checks without network access unless explicit Telegram/provider
confirmation flags are supplied. Discovery is a stopped-stack, polling-safe
read that does not mutate the cursor or allowlist. `up` waits for project-owned
PostgreSQL/Redis, migrates, bootstraps, then starts exactly one API, poller,
dispatcher, conversation, planning, and outbound runtime. `down` preserves
database data and stops only those demo-owned resources.

Acceptance is synthetic-first: fake `getMe`, provider, and Telegram delivery
prove bootstrap reconciliation, full durable ingress-to-outgoing-message flow,
replay idempotency, ignored disallowed chat handling, and active-webhook
polling refusal. A live manual test follows the runbook and requires explicit
operator-owned credentials; it must show a single reply in an allowlisted DM or
explicitly mentioned/replied-to private group message. Status and inspection
show safe IDs, states, counts, and categories, never raw payloads or secrets.
Inspection selects latest activity, Telegram update ID, internal incoming-update
UUID, conversation UUID, or platform chat ID. It orders jobs, actions, and
attempts deterministically; absent stages are reported as `not_created`.
