# January

Self-hosted social AI companion for Telegram.

**v0.1.0 — NOT YET PUBLISHED.** This source snapshot awaits independent
review. No release tag or official prebuilt image exists from this work. The
planned public repository is [hzjanuary/open-companion](https://github.com/hzjanuary/open-companion).

[Quality workflow](.github/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

January is a self-hosted Telegram AI companion designed for natural,
context-aware, durable conversations. Run it locally or on a VPS, choose a
model provider, and control how it participates, remembers and responds.

[Quick Start](#quick-start) · [Documentation](#documentation) ·
[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) ·
[Changelog](CHANGELOG.md) · [MIT License](LICENSE)

## What is January?

January joins private chats and Telegram groups with configurable personality,
selective replies and explicit memory. It can answer when mentioned or replied
to, participate selectively when enabled, or stay silent. You control the
conversation's response mode and the optional capabilities you enable.

Self-hosting is the primary distribution model: one source checkout, Docker
Compose and your own configuration. The backend supports OpenAI, Gemini, Groq,
OpenRouter and local Ollama. PostgreSQL keeps authoritative conversation and
work state; asynchronous workers process and deliver responses durably.

Privacy and safety are enforced through scoped access, user-controlled memory,
bounded retention and structural safety checks—not a promise of universal
security or comprehensive semantic moderation. External providers receive
content required for enabled requests. Local model inference does not make
Telegram a local messaging platform.

## Quick Start

The supported first-run path is Docker Compose with Telegram polling. You need
Docker Engine, Docker Compose with raw env-file support, a bot you control,
and a configured model provider. Host Python, uv, public HTTPS, Qdrant and
Graphify are not required for this path.

The [self-hosted quickstart](docs/runbooks/self-hosted-quickstart.md) is the
complete setup guide. Use the reviewed source archive during preparation.
Once the owner publishes the repository, the checkout commands will be:

```bash
git clone https://github.com/hzjanuary/open-companion.git
cd open-companion
umask 077
cp .env.self-host.example .env.self-host
chmod 600 .env.self-host
mkdir -p .local/self-host
cp docs/examples/self-host-provider-policy.json .local/self-host/provider-policy.json
./scripts/self-host-doctor.sh --offline --phase template
```

For persistent use, select a reviewed exact source revision. An extracted
source archive also works without Git history. Containers are built locally;
no official prebuilt registry image is claimed.

Build the setup image and generate missing local database/JWT secrets:

```bash
./scripts/self-host-compose.sh --profile tools build setup-tool
./scripts/self-host-compose.sh --profile tools run --rm --no-deps \
  --user "$(id -u):$(id -g)" setup-tool \
  python /app/self-host/setup_operator.py init
```

Next, follow the guide to
[configure your bot, model and explicit provider limits](docs/runbooks/self-hosted-quickstart.md#3-choose-credentials-model-and-explicit-limits).
Edit only the ignored private files. The example policy intentionally has
unconfirmed capabilities and unset limits; it is not ready to operate.

Complete the guide's
[authenticated setup](docs/runbooks/self-hosted-quickstart.md#4-initialize-authenticated-authority-and-canonical-scope)
before starting the bot. This operator-confirmed step verifies bot identity
with Telegram and creates canonical tenant/assistant/connection authority and
provider policies. Copying an env file or passing the doctor is not a substitute.

Once configuration and setup are complete:

```bash
./scripts/self-host-doctor.sh --offline --typed
./scripts/self-host-compose.sh --profile polling up -d --wait
curl --fail --silent --show-error http://127.0.0.1:8000/live
curl --fail --silent --show-error http://127.0.0.1:8000/ready
./scripts/self-host-compose.sh --profile polling ps
```

If you changed the host API port, use it in the health checks. `/live` reports
process life; `/ready` checks required database/schema and Redis dependencies,
not provider availability or a delivered conversation. Inspect service state
using the guide, then deliberately message your bot. That final user acceptance
contacts Telegram and your selected provider and may incur configured costs.

Do not run polling and webhook ingress simultaneously. Do not delete persistent
volumes to recover a setup problem. See
[troubleshooting](docs/runbooks/self-hosted-troubleshooting.md) and
[backup/upgrade guidance](docs/runbooks/self-hosted-upgrades.md).

## Features

Optional features need explicit configuration; they are not all enabled by the
minimal first-run profile.

### Conversations

- Configurable personalities and response modes, including mention/reply-based
  responses, optional selective ambient participation and pause controls.
- Bounded conversation context, authoritative direct-reply context and ordered
  delivery of longer answers.
- Schema-validated response plans and policy checks before platform actions.
- Reply-only `/regenerate` and private `/feedback helpful` or
  `/feedback unhelpful` controls.
  [Reply UX](docs/runbooks/telegram-conversation-ux.md) ·
  [Regeneration](docs/runbooks/telegram-regeneration.md) ·
  [Feedback](docs/runbooks/conversation-feedback.md)

### Memory & context

- Explicit, same-conversation memory with inspect, edit, recall and delete
  controls; bounded creator-private personal context in private chats.
- Optional short-lived conversation summaries and semantic retrieval of
  explicit memory.
- Optional operator-managed knowledge/RAG, with PostgreSQL source validation
  before reference text enters context.
  [Personal context](docs/runbooks/personal-context.md) ·
  [Summaries](docs/runbooks/conversation-summaries.md) ·
  [Semantic memory](docs/runbooks/semantic-memory.md) ·
  [Knowledge/RAG](docs/runbooks/knowledge-base-rag.md)

### Telegram

- Polling or HTTPS webhook ingress with durable inbox/outbox processing and
  idempotent update deduplication.
- Text, replies, mentions and stickers; optional bounded photo understanding
  and voice/audio transcription.
- Optional reply-only `/voice` playback through governed OpenAI TTS.
- Bounded typing presence, selective local reactions, private reminders and
  separately consented deterministic check-ins.
  [Media](docs/runbooks/telegram-media.md) ·
  [Voice](docs/runbooks/telegram-voice-tts.md) ·
  [Presence](docs/runbooks/telegram-presence.md) ·
  [Reactions](docs/runbooks/telegram-reactions.md) ·
  [Scheduling](docs/runbooks/proactive-scheduling.md)

### AI providers

- Five implemented chat adapters with configurable primary/fallback routing.
- Provider capability, health, rate/concurrency and explicit budget controls.
- Structured-output validation with bounded correction and safe fallback.
  [Routing and budgets](docs/runbooks/provider-routing-and-budgets.md)

### Safety & privacy

- Fail-closed authorization and tenant/assistant/conversation scope checks.
- Structural safety rules, targeting protection and fresh group authorization
  for administrator commands.
- User-controlled memory, export/erasure controls, bounded retention and
  content-safe telemetry.
  [Safety](docs/runbooks/safety-rate-limiting.md) ·
  [Data governance](docs/product/data-governance.md) ·
  [Encryption ownership](docs/product/encryption-ownership.md)

### Operations

- Durable work leases, idempotent processing and bounded recovery tools.
  Uncertain Telegram delivery is not blindly retried.
- Authenticated multi-tenant administration, offline configuration checks and
  explicit migrations.
- Backup/restore procedures, structured logs and optional loopback metrics.
  [Tenant administration](docs/runbooks/multi-tenant-administration.md) ·
  [Backup/restore](docs/runbooks/backup-restore.md) ·
  [Observability](docs/runbooks/observability.md)

## Architecture

January is a **modular monolith**: one repository with separately runnable API,
poller and worker processes, not independently owned microservices. FastAPI
serves HTTP; the Telegram adapter translates platform input and output.

```text
Telegram → polling / webhook → PostgreSQL inbox/outbox
                                      ↓
                             Redis work references
                                      ↓
                       conversation / planning workers
                                      ↓
                           validated response plans
                                      ↓
                          outbound worker → Telegram
```

PostgreSQL owns durable state. Redis provides work streams and coordination.
Optional Qdrant stores a rebuildable vector index whose results are revalidated
against PostgreSQL; it is not a source of canonical memory or knowledge.
Provider and Telegram calls happen outside database transactions. Ambiguous
delivery outcomes are recorded without claiming exactly-once delivery.

See [architecture and boundaries](docs/ARCHITECTURE.md) for details.

## Supported AI providers

| Provider | Chat adapter | Operator requirement |
| --- | --- | --- |
| OpenAI | Implemented | Model and API key |
| Gemini | Implemented | Model and API key |
| Groq | Implemented | Model and API key |
| OpenRouter | Implemented | Model and API key |
| Ollama | Implemented | Reachable local model server; no cloud key |

Choose a model compatible with the structured-response contract and declare
its capability and budget policy. Adapter support is not a promise of feature
parity across models. Ollama is not installed or downloaded automatically.
See [provider configuration](docs/runbooks/self-hosted-quickstart.md#provider-selection-and-bounded-local-ollama).

External LLM, transcription and TTS providers receive content needed for the
enabled requests. Self-hosting does not mean all data remains local. Ollama
allows local model inference, but Telegram remains an external messaging
platform.

## Self-hosting

- **Local Docker Compose:** polling-first, with private PostgreSQL/Redis and
  locally built application containers.
- **Single VPS:** the same source-based deployment, with deliberate secrets,
  backup and upgrade management.
- **Optional HTTPS webhook:** requires your own public endpoint, TLS and
  exclusive webhook ingress ownership.

There is no public managed SaaS or managed backup/support service. Community
support is best-effort. Qdrant, TTS and advanced operational profiles are
separate choices, not minimum text-chat prerequisites. Zalo is not currently
supported.

See [VPS deployment](docs/runbooks/self-hosted-vps.md),
[upgrades and backups](docs/runbooks/self-hosted-upgrades.md), and the
[self-host deployment policy](docs/product/self-hosted-deployment-profile.md).

## Documentation

| Start here | Guide |
| --- | --- |
| Quick Start | [Self-hosted first run](docs/runbooks/self-hosted-quickstart.md) |
| Configuration | [Credentials, providers and limits](docs/runbooks/self-hosted-quickstart.md#3-choose-credentials-model-and-explicit-limits), [full settings inventory](.env.example) |
| VPS | [Polling and optional webhook](docs/runbooks/self-hosted-vps.md) |
| Upgrades / backup | [Self-hosted upgrades and recovery](docs/runbooks/self-hosted-upgrades.md) |
| Troubleshooting | [Self-host diagnostics](docs/runbooks/self-hosted-troubleshooting.md) |
| Architecture | [Module boundaries and runtime shape](docs/ARCHITECTURE.md) |
| Privacy | [Data governance](docs/product/data-governance.md), [encryption ownership](docs/product/encryption-ownership.md) |
| Security | [Reporting and safe diagnostics](SECURITY.md) |
| Contributing | [Contribution guide](CONTRIBUTING.md) |
| Maintainer tooling | [Optional Graphify navigation](docs/maintainers/graphify.md) |

The [documentation index](docs/README.md) links the detailed operational and
product references. [CHANGELOG.md](CHANGELOG.md) records user-facing changes.

## Development

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). From a source checkout:

```bash
uv sync --all-groups --locked
./scripts/validate.sh
```

Canonical tests use synthetic inputs and fake external adapters, not real bot
tokens or paid model keys. Broad integration additionally needs disposable
PostgreSQL/Redis/Qdrant fixtures and the locally built stock acceptance image;
follow [local development](docs/runbooks/local-development.md) and
[CONTRIBUTING.md](CONTRIBUTING.md) before running it. Do not point validators at
meaningful deployment data.

## Contributing

Bug reports, documentation improvements and code contributions are welcome.
[CONTRIBUTING.md](CONTRIBUTING.md) explains setup, scope, review and validation.
No maintainer account or live Telegram/provider access is required.

## Security

Read [SECURITY.md](SECURITY.md) before reporting a vulnerability or sharing
diagnostics. Never post tokens, private conversations, prompts or unredacted
configuration in issues. No universal security, regulatory compliance or
end-to-end encryption guarantee is claimed.

## Optional maintainer tooling

Maintainers can optionally use the pinned
[Graphify integration](docs/maintainers/graphify.md) for local codebase
navigation. Its default is code-only/local. It is not application runtime,
a self-host dependency or a contributor requirement; verify graph findings
against authoritative source.

## License

Licensed under the [MIT License](LICENSE). Third-party material retains its
own licenses; see [NOTICE](NOTICE). Provider/platform names describe
integrations, not affiliation or endorsement.
