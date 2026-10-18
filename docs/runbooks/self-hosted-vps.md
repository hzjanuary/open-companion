# Self-hosted single VPS

Run the same guarded Docker Compose installation on one Linux VPS. Polling is
the simplest profile: Telegram connects outbound, so it needs no public bot
HTTP endpoint, domain, TLS certificate or reverse proxy. This is a single-host
deployment, not a high-availability or throughput guarantee. Resource use
depends on enabled workers, the selected model and optional Qdrant.

Start with the [quickstart](self-hosted-quickstart.md), including its source
identity and MIT license notice. Install Docker Engine and a
Compose plugin capable of `env_file` `format: raw` using their supported host
procedures. Use a normal operator account with intentionally provisioned Docker
access or a configured rootless host. Docker-group access is privileged; never
relax socket permissions, run the app as root, or rely on a desktop session.

## Polling installation

Obtain a containing, reviewed source revision; pin its exact SHA or a future
published tag. Follow quickstart steps 2–4 to copy/restrict configuration, build,
generate local secrets, choose the bot/provider and finite policies, and
establish authenticated tenant/Assistant/connection authority. No private
registry, corporate approval, IdP or monitoring subscription is required.

Then run from that checkout:

```bash
./scripts/self-host-doctor.sh --offline --typed
./scripts/self-host-compose.sh --profile polling up -d --wait
curl --fail --silent --show-error http://127.0.0.1:8000/live
curl --fail --silent --show-error http://127.0.0.1:8000/ready
./scripts/self-host-compose.sh --profile polling ps
```

Use your configured `JANUARY_HOST_PORT` instead of 8000 if changed. Keep the
Compose project name and checkout location stable across operations; changing
them can select a different project/volume rather than upgrade the old one.
If you choose an explicit `-p NAME`, use it in **every** wrapper operation.
An occupied port is not permission to stop an unrelated stack.

The API binds only to host loopback. PostgreSQL, Redis and optional Qdrant have
no published host ports in `compose.self-host.yaml`. Permit only your chosen
SSH/operator access through host/cloud firewalls. Polling needs outbound DNS,
Telegram HTTPS and the selected hosted-provider HTTPS, or a reachable local
model server. Do not open database/vector ports to make a container connect.
Docker's published-port rules and your host firewall must both be understood;
do not assume a generic firewall rule makes an all-interface publication safe.

The authenticated control API stays local/internal. HS256 issuer/audience,
expiry, deployment roles and active tenant-owner roles remain mandatory.
The setup API has no host port and must be stopped after initialization. If you
deliberately publish another API surface, provide your own valid TLS and access
boundary; do not make the controls anonymous for convenience.

Compose restarts long-running services unless stopped; migration is a one-shot
dependency, not a restart loop. Verify required workers after host reboot or
maintenance. `/live` is process life and `/ready` is bounded schema/dependency
readiness, not proof of credentials, policies, ingress ownership or delivery.
Review [troubleshooting](self-hosted-troubleshooting.md) for bounded local logs.

## Optional public webhook

Choose this only when you intend to operate a public HTTPS endpoint. Arrange
your chosen public hostname, valid certificate and reverse proxy/ingress first.
The repository does not install DNS/TLS/proxy infrastructure for you. Forward
`/api/v1/platforms/telegram/webhook/CONNECTION_UUID` to the same path on the
loopback API, replacing `CONNECTION_UUID` with the persisted
`JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID`. Preserve POST bodies and
`X-Telegram-Bot-Api-Secret-Token`; do not publish the control routes by accident.
Expose only intentional HTTPS (and any operator-selected certificate setup
requirement), never PostgreSQL/Redis/Qdrant. Do not disable TLS verification.

An existing polling installation already has canonical IDs/policies. Stop its
ingress before changing `.env.self-host`:

```bash
./scripts/self-host-compose.sh --profile polling stop poller
```

Allow already accepted durable work to drain under your operator's observation,
then stop other application writers before the switch. Set
`JANUARY_TELEGRAM_DELIVERY_MODE=webhook`, a chosen
`JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL=https://YOUR_PUBLIC_HOST` (no webhook
path suffix), and a private strong `JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN`.
Preserve canonical IDs, local auth and provider policies. On a new installation,
use the same setup phase but pass `--profile webhook` to the doctor; the private
setup API still performs no ingress/webhook mutation.

```bash
./scripts/self-host-doctor.sh --offline --profile webhook --typed
./scripts/self-host-compose.sh --profile webhook up -d --wait
curl --fail --silent --show-error http://127.0.0.1:8000/ready
./scripts/self-host-compose.sh --profile webhook ps
```

Webhook profile contains no poller. Before opening traffic, confirm the old
owner is stopped and the public path/certificate/header forwarding is correct.
Registration is a separate deliberate **live Telegram mutation**, never a
startup/doctor/Quality side effect:

```bash
./scripts/self-host-compose.sh --profile webhook exec -T backend \
  python -m app.runtime.telegram_connection_operations webhook-inspect \
  --confirm-live-telegram --json
./scripts/self-host-compose.sh --profile webhook exec -T backend \
  python -m app.runtime.telegram_connection_operations webhook-register \
  --confirm-live-telegram --json
./scripts/self-host-compose.sh --profile webhook exec -T backend \
  python -m app.runtime.telegram_connection_operations mode-verify \
  --confirm-live-telegram --json
```

These existing operations verify persisted active bot authority and resulting
Telegram state. A different active webhook is a conflict; registration does
not silently steal it. Output can identify your bot/URL and contain Telegram's
diagnostic text: review locally and redact before sharing. Validate delivery by
a deliberate optional message only after readiness/ownership checks.

To return to polling, close/drain public ingress and stop the application
workers first; retain the private backend only for the bounded management
operation below. An authorized operator may remove the selected webhook:

```bash
./scripts/self-host-compose.sh --profile webhook exec -T backend \
  python -m app.runtime.telegram_connection_operations webhook-delete \
  --confirm-live-telegram --confirm-delete-webhook --json
```

Do **not** add `--drop-pending-updates`: default deletion preserves pending
updates. Verify empty Telegram webhook state, stop the webhook application,
change delivery mode back to polling, run the polling doctor, then start exactly
one poller. If the backend was stopped first, run the same operation with
`run --rm --no-deps backend` instead of `exec -T backend`, retaining live
confirmation and the existing database. Never run both ingress profiles at once.

## State and maintenance

`january-self-host-postgres` is the Compose logical authoritative volume;
Docker normally prefixes it with the project name. Redis has no persistent
volume: leases, streams and counters are reconstructible coordination, not
business truth. `january-self-host-qdrant` is optional derived state. Raw media
is bounded/ephemeral; voice artifacts are short-lived PostgreSQL BYTEA, not a
fictional permanent media volume. Optional Ollama model weights are a separate
cache, not conversation authority.

For meaningful VPS data, strongly prefer verified encrypted PostgreSQL backups,
protected private configuration, and an external post-backup erasure record.
No enterprise backup approval is required. Use [backup, restore and upgrades](self-hosted-upgrades.md)
before maintenance; never delete meaningful volumes or restore over live data.
External monitoring is optional; local metrics and bounded health/service checks
remain available. Stricter [production operations](production-operations.md)
are a downstream option, not an ordinary self-host prerequisite.
