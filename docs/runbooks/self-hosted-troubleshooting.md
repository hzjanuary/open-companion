# Self-hosted troubleshooting

Start with the selected-profile offline doctor, then running service state and
bounded local logs. No diagnostic result grants authority to erase volumes,
bypass policy, rotate another bot's webhook or retry ambiguous external sends.
The [quickstart](self-hosted-quickstart.md) is polling-first; use webhook arguments
only when that mode is deliberately configured.

```bash
./scripts/self-host-doctor.sh --offline
./scripts/self-host-compose.sh --profile polling ps
./scripts/self-host-compose.sh --profile polling logs --tail 50 backend poller
curl --fail --silent --show-error http://127.0.0.1:8000/live
curl --fail --silent --show-error http://127.0.0.1:8000/ready
```

Use your actual `JANUARY_HOST_PORT`. Exit 0 from the default doctor is only
static file/profile/Compose readiness; complete Settings/policy typing requires
explicit `--typed` and an already built image. Neither check tests a live DB,
model, Telegram, persisted policies, ownership or delivery. `/live` is process
life; `/ready` checks required PostgreSQL revision/Redis, not the whole bot.
No optional disabled Qdrant/TTS/model server is a hidden readiness dependency.

## Evidence and safe next actions

| Symptom or evidence | Check and bounded recovery |
| --- | --- |
| Docker command absent | Install Docker Engine/CLI through the supported host procedure; default doctor never auto-installs or starts a daemon. |
| Compose plugin absent/raw-file render rejected | Check `docker compose version`; install a plugin supporting the actual raw env representation. Do not convert it to a sourced shell file. |
| Docker engine/access fails during build or `--typed` | Check the selected Docker context/daemon and intentionally provisioned operator access/rootless setup. Default static doctor can pass without a daemon. Do not relax socket permissions or run the app as root. |
| Private config missing, permissive, symlinked, duplicate or malformed | Copy the minimal example to `.env.self-host`, keep it a regular ignored file, use `chmod 600`, LF raw assignments without outer shell quotes, and remove duplicate/unknown names. Never print the file in a report. |
| Template/pre-ID setup rejected | Use `--phase template` only before filling secrets/policy, or `--phase setup` before IDs exist. They do not prove a running bot. Default runtime phase correctly requires canonical IDs and cleared bootstrap subjects. |
| Loopback API port occupied | Set `JANUARY_HOST_PORT` in the private file, run the doctor, recreate the selected project's backend and use that port. Do not stop unrelated containers. Data services need no self-host host ports. |
| PostgreSQL not healthy | Inspect selected `database` state and bounded logs. Verify its volume/name/user and private password locally. Changing a file's password does not change an already initialized PostgreSQL role; do not erase a meaningful volume to force it. |
| Redis not healthy or coordination unavailable | Inspect `redis` state and connectivity on the project network. Guarded chat needs Redis even though its state is transient. Restore service, not bypass rate/concurrency or delivery ownership. |
| Migration fails or readiness reports wrong schema | Keep ingress/workers stopped. Inspect bounded `migration` logs and exact target/current head. Use the single reviewed migration owner and [upgrade guide](self-hosted-upgrades.md); no destructive downgrade or manual `alembic_version` update. |
| Telegram token missing/placeholder | Default doctor blocks before startup. Choose the intended bot's private token, run setup-phase checks, then explicitly confirm identity using the setup procedure. Never paste a Bot API token-bearing URL. |
| Telegram authentication/permission error | Existing adapter classifies failures; inspect only the closed error class and active canonical bot/connection authority. Offline checks cannot verify a token. Deliberate live verification is separate and never sends a message. |
| Poller exits on active webhook/conflict or cannot own ingress | Inspect the chosen connection/mode and the old owner's state. Stop/drain the old owner; use explicit confirmed lifecycle operations in the [VPS guide](self-hosted-vps.md). Preserve pending updates. Never start both ingress profiles or multiple pollers to bypass ownership. |
| API healthy but bot silent | Check every required worker, active tenant/Assistant/connection, conversation eligibility and current provider route/health/hard budget. Silence can be a valid plan; API health is not admission/delivery. No legacy-mode, anonymous control or raw-send escape. |
| Missing provider model/key | Configure only the selected actual provider and schema-capable model. A non-OpenAI text provider needs no hidden OpenAI/TTS key. Ollama is keyless but needs reachable model service, not container-local host loopback. |
| Provider timeout, stale health, depleted hard budget or policy conflict | Inspect closed admission/error/recovery classes and existing authenticated policies. First-run health is owner affirmation with staleness, not a live probe. Preserve immutable attempts/accounting; do not declare free prices, raise budgets, refresh health or revive a disabled resource automatically. |
| Optional summary/vector/scheduler worker absent | Feature flags alone do not start a service. Enable the complete feature/worker/profile pair and selected workload's governed provider/embedding configuration, or deliberately disable the pair. See the quickstart's optional capability section. |
| Qdrant enabled but unavailable | Restore private Qdrant/embedding connectivity for selected semantic/knowledge workers. Retrieval falls back safely but index/rebuild acceptance still needs proof. Rebuild from current PostgreSQL after erasure reconciliation, never treat old vectors as authority. Disabled features need no Qdrant. |
| TTS disabled/unavailable | Ordinary text chat needs no TTS. For deliberate `/voice`, check OpenAI key, existing TTS capability/route/budget, authoritative retained reply and closed outcome. Do not synthesize again on uncertain I/O or restore expired/erased bytes. |
| Worker restarting/not running | Inspect that service's bounded logs/configuration and dependencies. `runtime.py` permits only existing worker names; invalid Settings fail redacted. Restore the required service graph, not a supervisor/demo shortcut. |
| Setup interrupted/conflicting | Retain original config/policy/effective time; unchanged retries use stable mutation IDs. Conflicting existing scope/route/budget or disabled resources require deliberate authenticated review. Do not rerun init over a different source file or wipe state. |

## Logs and support

Inspect only the affected service locally, e.g.:

```bash
./scripts/self-host-compose.sh --profile polling logs --tail 50 \
  dispatcher conversation-worker planning-worker command-worker outbound-worker \
  provider-governance-worker governance-worker retention-worker
./scripts/self-host-compose.sh --profile polling config --quiet
./scripts/self-host-compose.sh --profile polling config --services
```

January logging is content-safe by contract, but surrounding Docker/database/
proxy errors and existing explicit live evidence can still identify resources.
Do not enable SQL echo/root HTTP debug or assume every third-party log is safe
to publish. The wrapper blocks accidental full `config` dumps; no giant support
bundle is added. Do not upload full `.env`, config JSON, provider bodies, prompts,
conversations, backups, tokens or token-bearing URLs.

Safe reviewed support information is the containing version/source SHA, service
name/state, redacted error class, migration head, doctor scope/output, and local
health status. Keep real bot/account IDs, hostnames and private resource metadata
out unless deliberately needed in a verified private channel. See
[security reporting](../../SECURITY.md): private reporting availability is
unverified; never publish sensitive vulnerability detail to obtain help.

Canonical tests and the self-host validator use fake external boundaries and
need no real provider/Telegram/TTS credentials. Run test validators only on
isolated synthetic infrastructure, not a personal/VPS database. Optional live
acceptance is an operator choice after readiness/admission/ownership, and may
incur provider cost. Recovery keeps PostgreSQL authority, privacy erasure,
idempotency, single ingress ownership and terminal uncertain delivery intact.
