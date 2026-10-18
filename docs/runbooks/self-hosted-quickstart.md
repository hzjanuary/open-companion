# Self-hosted quickstart

The simplest supported installation is a locally built Docker Compose bot using
Telegram polling. It needs PostgreSQL, Redis, the existing API/core workers,
a Telegram bot token and one chosen model/provider. It does not need public
HTTPS, DNS, a reverse proxy, Qdrant, TTS, a monitoring vendor or a corporate
operator. You are the operator; safety, privacy, authority and finite provider
budgets still apply.

Source notice: use a reviewed checkout or GitHub-style source archive containing
this guide, `compose.self-host.yaml` and the self-host scripts. SPEC-043 is
committed; SPEC-044 release work is a candidate, not a published tag. Repository
access and later publication remain owner-controlled. A downloaded archive
needs no Git history for the Docker path; retain its exact source identity.

License: [MIT](../../LICENSE), selected during SPEC-044. See
[CHANGELOG](../../CHANGELOG.md) for changes and the
[release policy](../maintainers/release-process.md) for publication status.

## 1. Obtain the checkout and tools

With repository access (or after the owner makes it public), the clone route is:

```bash
git clone https://github.com/hzjanuary/open-companion.git
cd open-companion
test -f compose.self-host.yaml
```

For meaningful persistent use, pin the reviewed exact commit SHA (or a future
published release tag), not an assumed release or floating image identity.
The first public tag remains an owner decision; the package's `0.1.0` field is
not evidence of a published release. An archive is an alternative to cloning.

Commands below use Bash/POSIX file permissions, Docker Engine and the Docker
Compose plugin with `env_file` `format: raw` support. The doctor checks whether
your plugin can render the actual file. Use normal operator Docker access or
a deliberately configured rootless host; Docker-group access is privileged.
Do not relax socket permissions or run the application as root. No desktop GUI,
host Python, host UV or existing virtualenv is needed for this Docker path.
The shown host HTTP checks use `curl`; install it if absent or inspect the
Compose API healthcheck, which uses Python's standard library inside the image.

## 2. Copy private configuration and build

Run from the repository root in a checkout owned by your normal operator user:

```bash
umask 077
cp .env.self-host.example .env.self-host
chmod 600 .env.self-host
mkdir -p .local/self-host
cp docs/examples/self-host-provider-policy.json .local/self-host/provider-policy.json
./scripts/self-host-doctor.sh --offline --phase template
./scripts/self-host-compose.sh --profile tools build setup-tool
./scripts/self-host-compose.sh --profile tools run --rm --no-deps \
  --user "$(id -u):$(id -g)" setup-tool \
  python /app/self-host/setup_operator.py init
```

`init` explicitly generates only missing random local PostgreSQL/JWT secrets,
retains existing values and atomically restricts the private file to mode 600.
It makes no network calls. The explicit Compose operation may create a local
network/container; it starts no dependencies. The image is built locally from
locked dependencies on Python 3.12 and runs the normal application non-root.
Builds may need public base-image/package connectivity; no private registry is
required. A prebuilt cached image can perform the init/check operations offline.

Use `self-host-compose.sh` for this representation rather than sourcing the file
or passing it as Compose's interpolation `.env`: the wrapper preserves literal
dollars in database/image/port fields and ignores unrelated inherited January
settings. Other application values enter through the raw env file. Never use
shell expansion or outer quotes in this file; JSON arrays/objects are raw JSON,
without an extra pair of shell quotes. `.env.example` remains the full typed
inventory for native development, not a file to source into this path.

## 3. Choose credentials, model and explicit limits

Edit only the ignored `.env.self-host`, never an example/source file. The core
minimum is:

| Input | What to set |
| --- | --- |
| Local database/JWT secrets | generated above; preserve privately |
| `JANUARY_TELEGRAM_BOT_TOKEN` | token for the bot you deliberately selected/created |
| `JANUARY_LLM_PRIMARY_PROVIDER` | `openai`, `gemini`, `groq`, `openrouter` or `ollama` |
| Chosen `JANUARY_LLM_<PROVIDER>_MODEL` | actual model supporting the structured response contract |
| Chosen hosted `JANUARY_LLM_<PROVIDER>_API_KEY` | corresponding key; only for that hosted provider |
| `JANUARY_LLM_OLLAMA_BASE_URL` | only for Ollama: a model server reachable from the application container |

Ollama needs no cloud key but is not automatically installed or downloaded. Its
container-local `127.0.0.1` is not your host; use the explicit bounded local
recipe below or your own reviewed reachable arrangement. No feature/model
parity is promised. OpenAI credentials are not needed for text chat under another provider.
Keep TTS/media/summaries/semantic/knowledge/scheduling off for this first run.

Leave tenant/connection IDs blank initially. Keep polling, command/outbound
workers and the guarded engineering controls as in the minimal example. The
self-host representation forces safety, rate/concurrency, enforced provider
governance/recovery, authenticated control, privacy/governance and retention.
PostgreSQL/Redis addresses are internal and need no public host ports.

Fill `.local/self-host/provider-policy.json` yourself before setup:

- Confirm the selected model supports the required JSON-schema response and
  set `json_schema_supported` to true only after that decision.
- Use `local` data class for Ollama or explicitly affirmed `approved_external`
  for a hosted model. This is a data-boundary choice, not a provider probe.
- Set integer input/output prices in microUSD per million tokens using your
  actual chosen provider/model rates. Zero is an explicit price decision, not
  a supplied free-price default; local models also need a declared policy.
  A zero-price estimated-cost budget does not cap request/token counts; choose
  an explicit count/token hard budget when that is the intended bound.
- Supply all health thresholds/staleness values, a current/past explicit UTC
  `effective_at`, and at least one finite hard budget with an explicit amount
  and alert threshold. Actual measurements include requests, token counts or
  estimated microUSD; windows are `daily_utc`/`monthly_utc`.

The supplied JSON intentionally contains null limits and unconfirmed schema
support; it must fail until filled. Do not treat fixture prices/limits from tests
as operational recommendations. No model, spend allowance or current vendor
price is selected for you. Advanced fallback/optional-workload policies use the
existing authenticated controls; first-run setup publishes only the primary
chat policy.

Check without contacting a database, Telegram or a provider:

```bash
./scripts/self-host-doctor.sh --offline --phase setup
./scripts/self-host-doctor.sh --offline --phase setup --typed
```

The default doctor only reads private files, inspects static migration markers
and quietly renders Compose; it does not create Docker resources. `--typed` is
explicit: it requires the already built local image, creates/removes one
non-root, read-only, network-disabled container and applies the actual Settings/
policy validators. It never pulls, builds, migrates or probes live services.
Exit 0 proves only the selected offline checks. Nonzero is a blocker; disabled
optional absence is not. Neither result verifies persisted authority, provider
availability, the running worker graph or delivered messages.

## 4. Initialize authenticated authority and canonical scope

This next section is a deliberate live operator step, not canonical offline
acceptance. The setup tool verifies Telegram bot identity (`getMe`) only after
both confirmation flags. It never sends a message, invokes a model, changes a
webhook, creates a provider account or changes DNS.

```bash
./scripts/self-host-compose.sh --profile setup up -d --wait operator-api
./scripts/self-host-compose.sh --profile tools run --rm --no-deps \
  --user "$(id -u):$(id -g)" setup-tool \
  python /app/self-host/setup_operator.py setup \
  --confirm-operator-setup --confirm-live-telegram
./scripts/self-host-compose.sh --profile setup stop operator-api
```

The first command starts private PostgreSQL/Redis, a sole bounded migration to
`0026_conversation_feedback`, and the internal authenticated setup API. It has
no host API port, Telegram ingress, model generation or delivery enabled.
Migration failure prevents dependent startup; there is no SPEC-043 migration.

The explicit facade signs a short-lived local HS256 token with your configured
issuer/audience/subject/expiry. Existing API rules establish initial deployment
authority only in the authorized empty-set bootstrap case, then create your
tenant and its owner membership. Existing trusted local bot reconciliation
binds an active Assistant/connection; no default-tenant/raw policy SQL shortcut
is used. Existing provider controls persist capability, price, current health,
exact route and hard budgets with optimistic revisions/idempotency.

On complete success, the private file receives real canonical tenant/connection
IDs and `JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS=[]`. Keep that file
private. First-run READY health is your explicit operating-owner affirmation,
not a successful provider probe. Health staleness and hard admission remain in
force. A repeat does not refresh health or silently enable a disabled resource.

If setup is interrupted, keep its original configuration/policy/effective time
and inspect the redacted error/current authenticated state. An unchanged retry
can recover through the existing idempotency contract. Changed authority,
disabled/inactive resources or different routing/budgets are conflicts, not
permission to overwrite state or repeatedly create new policies. No blind reset,
volume deletion or legacy-mode escape is part of recovery.

## 5. Start, verify, then deliberately use the bot

```bash
./scripts/self-host-doctor.sh --offline --typed
./scripts/self-host-compose.sh --profile polling up -d --wait
curl --fail --silent --show-error http://127.0.0.1:8000/live
curl --fail --silent --show-error http://127.0.0.1:8000/ready
./scripts/self-host-compose.sh --profile polling ps
```

This starts API, poller, dispatcher, conversation/planning/command/outbound
workers, provider recovery, privacy/governance and retention, plus PostgreSQL/
Redis and the completed migration. Qdrant and optional workers are absent.
`JANUARY_HOST_PORT` changes the loopback API host port; container port remains
8000. Use the selected port in local checks. Persistent PostgreSQL is the
authoritative volume; no separate permanent raw-media volume exists.

`/live` means process life. `/ready` checks the exact PostgreSQL revision and
Redis required by enabled coordination. It does not test credentials, policies,
Qdrant when disabled, provider health or end-to-end bot delivery. Compose wait
also does not establish worker ownership or a successful generated response.
Inspect required service state and bounded local logs:

```bash
./scripts/self-host-compose.sh --profile polling logs --tail 50 \
  backend poller dispatcher conversation-worker planning-worker \
  command-worker outbound-worker provider-governance-worker \
  governance-worker retention-worker
```

Do not enable debug/SQL echo, dump full configuration, or post unredacted logs,
tokens, model prompts or private conversations in an issue. The wrapper refuses
accidental secret-bearing `config` dumps; use `config --quiet` or its safe
metadata selectors. See [security reporting](../../SECURITY.md) before sharing
diagnostics or vulnerability details.

Only after these checks, open the verified bot and deliberately send a message.
That optional user acceptance contacts Telegram/the chosen provider and may
incur the operator's configured costs. It is not part of provider-free canonical
Quality. Polling needs outbound connectivity but no inbound Telegram HTTP;
it refuses a configured live webhook and never removes one automatically.
Exactly one ingress owner is required. Do not start both profiles or multiple
pollers to force recovery.

For disposable testing, stop without erasing data:

```bash
./scripts/self-host-compose.sh --profile polling stop
```

Do not use volume-deleting commands on meaningful data. Persistent personal
instances should have protected PostgreSQL backups; meaningful VPS data should
strongly prefer them. Redis/Qdrant are not authoritative backups. Upgrade and
restore require explicit quiescence, migration/authority checks and erasure/
derived-state reconciliation, not a live database overwrite or downgrade promise.

See the [deployment policy](../product/self-hosted-deployment-profile.md) for
the supported local/VPS profiles, mandatory engineering contracts and optional
capability matrix. Optional webhook/public HTTPS, vector indexing, TTS and
advanced operational work are separate choices, not first-run prerequisites.

## Provider selection and bounded local Ollama

The actual text adapters use the following Settings. Set the primary provider
and only its model/key; omitted hosted base URLs retain the typed defaults below.
Do not put a token in a URL or assume an arbitrary compatible endpoint/model
has the required JSON-schema capability. Provider-free tests prove adapter and
policy behavior, not current vendor/model availability, pricing or account terms.

| Provider | Model | Credential | Base URL setting and default |
| --- | --- | --- | --- |
| `openai` | `JANUARY_LLM_OPENAI_MODEL` | `JANUARY_LLM_OPENAI_API_KEY` | `JANUARY_LLM_OPENAI_BASE_URL=https://api.openai.com/v1` |
| `gemini` | `JANUARY_LLM_GEMINI_MODEL` | `JANUARY_LLM_GEMINI_API_KEY` | `JANUARY_LLM_GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta` |
| `groq` | `JANUARY_LLM_GROQ_MODEL` | `JANUARY_LLM_GROQ_API_KEY` | `JANUARY_LLM_GROQ_BASE_URL=https://api.groq.com/openai/v1` |
| `openrouter` | `JANUARY_LLM_OPENROUTER_MODEL` | `JANUARY_LLM_OPENROUTER_API_KEY` | `JANUARY_LLM_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1` |
| `ollama` | `JANUARY_LLM_OLLAMA_MODEL` | none | `JANUARY_LLM_OLLAMA_BASE_URL`; native default `http://127.0.0.1:11434` must change for Docker |

Hosted choices require outbound HTTPS to the selected endpoint and applicable
operator account/cost decisions. Ollama uses the existing `/api/chat` adapter;
model response-schema support is an explicit capability decision. Optional
fallback uses `JANUARY_LLM_FALLBACK_PROVIDER` plus its own model/key and governed
policies; it must differ from primary. The bounded first-run facade publishes
only primary chat policy, not all fallback/media/embedding/TTS workloads.

For a new local Ollama installation, this explicit recipe attaches a separately
owned CPU model container to the existing Compose network, without publishing
11434. Use `-p january-personal` in **every** self-host wrapper command starting
with step 2; the one-shot init creates `january-personal_default`. Do not rename
an existing project's identity/volumes: substitute its deliberately verified
project name throughout instead. These operations are optional, resource- and
network-mutating operator steps, not canonical validation:

```bash
docker network inspect january-personal_default >/dev/null
read -r -p 'Reviewed ollama/ollama image digest (ollama/ollama@sha256:...): ' ollama_image
[[ "$ollama_image" =~ ^ollama/ollama@sha256:[a-f0-9]{64}$ ]]
docker run -d --name january-personal-ollama \
  --network january-personal_default --network-alias ollama \
  --restart unless-stopped \
  --volume january-personal-ollama-models:/root/.ollama "$ollama_image"
docker exec january-personal-ollama ollama list
read -r -p 'Deliberately selected schema-capable chat model: ' ollama_model
test -n "$ollama_model"
docker exec january-personal-ollama ollama pull "$ollama_model"
docker exec january-personal-ollama ollama list
```

Choose a compatible image/model yourself; no floating image, model size, GPU
setup or performance/parity guarantee is supplied. Image/model downloads need
connectivity/storage. A name collision must fail, not replace another container.
In the private config set primary `ollama`, its selected model and
`JANUARY_LLM_OLLAMA_BASE_URL=http://ollama:11434`, with policy data class `local`.
Then continue setup-phase doctor/typed checks and normal setup/start using the
same project. The model cache is not conversation authority. This separately
owned container is not a fictitious mandatory Compose service and is not stopped
by Compose: stop it explicitly with `docker stop january-personal-ollama` when
that is your selected maintenance scope; retain its cache unless deliberately
disposable. Host-installed Ollama needs a separately secured reachable address;
do not expose an unauthenticated model endpoint publicly to fix loopback.

The container/cache layout follows [Ollama Docker documentation](https://docs.ollama.com/docker);
the project network/name resolution follows [Docker Compose networking](https://docs.docker.com/compose/how-tos/networking/).
No Ollama image/model was downloaded or live inference performed by canonical
tests. This is an explicit operator path, not tested model feature parity.

## Optional capabilities

Leave these off until core chat works. A flag alone never starts its worker.
Enable each complete Settings pair and corresponding Compose/doctor profile,
and publish the selected workload's existing enforced policies before real I/O:

| Choice | Settings pair or prerequisite | Compose profile and doctor selector |
| --- | --- | --- |
| Summaries | `JANUARY_CONVERSATION_SUMMARIES_ENABLED=true`, `JANUARY_SUMMARY_WORKER_ENABLED=true`; governed summary provider | `--profile summaries`; doctor `--enable summaries` |
| Semantic memory | `JANUARY_SEMANTIC_MEMORY_ENABLED=true`, `JANUARY_SEMANTIC_MEMORY_WORKER_ENABLED=true`; Ollama embedding/Qdrant | `--profile semantic-memory`; doctor `--enable semantic-memory` |
| Knowledge RAG | `JANUARY_KNOWLEDGE_RAG_ENABLED=true`, `JANUARY_KNOWLEDGE_INDEX_WORKER_ENABLED=true`; Ollama embedding/Qdrant and scoped knowledge | `--profile knowledge-rag`; doctor `--enable knowledge-rag` |
| Scheduling | `JANUARY_PROACTIVE_SCHEDULING_ENABLED=true`, `JANUARY_SCHEDULER_WORKER_ENABLED=true`; command/outbound workers | `--profile scheduling`; doctor `--enable scheduling` |
| Qdrant only | private derived server, not sufficient to enable retrieval | `--profile qdrant`; doctor `--enable qdrant` |

Vector features require actual `JANUARY_EMBEDDING_PROVIDER=ollama`, selected
`JANUARY_EMBEDDING_MODEL`, matching `JANUARY_EMBEDDING_DIMENSION`, and reachable
`JANUARY_LLM_OLLAMA_BASE_URL`. Both vector profiles include private Qdrant and
their actual worker. Keep the normal polling/webhook profile as well. For
example, after deliberate complete semantic configuration/policy:

```bash
./scripts/self-host-doctor.sh --offline --typed --enable semantic-memory
./scripts/self-host-compose.sh --profile polling --profile semantic-memory up -d --wait
```

Typed/static checks do not publish optional-workload policies or verify the
external service. See [summaries](conversation-summaries.md),
[semantic memory](semantic-memory.md), [knowledge RAG](knowledge-base-rag.md)
and [scheduling](proactive-scheduling.md) for their actual authority/lifecycle
operations. Disable both flags and stop the optional worker when withdrawing
that capability; do not leave a half-enabled path.

TTS is independent of ordinary text chat. Deliberate
`JANUARY_TELEGRAM_VOICE_TTS_ENABLED=true` requires an OpenAI key, existing enforced
TTS capability/route/budget and retained authoritative `/voice` reply target.
External synthesis may incur cost. Artifacts are bounded PostgreSQL BYTEA,
purged after the 24-hour terminal-delivery grace or seven-day hard maximum,
and immediately on erasure; raw input media is ephemeral. No permanent media
volume or automatic regeneration from erased/expired bytes exists. See
[voice operations](telegram-voice-tts.md) and [media operations](telegram-media.md).

Continue with [VPS polling or optional webhook](self-hosted-vps.md),
[backup/restore and upgrades](self-hosted-upgrades.md), or
[troubleshooting](self-hosted-troubleshooting.md). Native development uses the
separate Python 3.12/UV [local-development guide](local-development.md), not the
minimal raw self-host file or a second bot installation shortcut.

## Contributor synthetic proof

Do not run repository validators on a personal database. The self-host
distribution validator renders configuration and runs hermetic tests only:

```bash
./scripts/validate-self-hosted.sh
```

Contributors need the separate Python 3.12/UV development environment for that
command; these are not host prerequisites for the Docker installation above.
To rehearse the complete stock first-run flow with closed fake HTTP boundaries:

```bash
docker build --tag january-self-host:spec043-development .
uv run pytest -m integration -q -s backend/tests/integration/test_self_host_runtime.py
```

This Linux Docker proof creates a unique project with a fresh PostgreSQL volume,
Redis, all core workers and an internal-only network. It verifies authenticated
setup, polling cursor/restart/replay, webhook secret/dedup, governed delivery
and credential/content-safe logs; it makes no real Telegram/provider calls.
It separately checks the normal bridge's loopback API publication after
quiescing all I/O workers, then removes only its owned resources. CI explicitly
builds the test image and includes this test in its existing integration
selection. Synthetic acceptance does not replace your deliberately chosen
live bot/provider test or prove model availability, price or feature parity.
