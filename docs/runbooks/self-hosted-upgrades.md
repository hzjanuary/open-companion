# Self-hosted backup restore and upgrades

PostgreSQL is authoritative for tenants, Assistants, connections, conversations,
privacy tombstones, inbox/outbox/cursors, provider policies/accounting, recovery,
memory, knowledge, schedules, feedback and bounded voice artifacts. Redis is
transient coordination; Qdrant is derived/rebuildable. Backing up only either
of those is not recovery. This guide uses the existing PostgreSQL tools in the
self-host database container, without corporate restore/backup approvals.

Backups are optional for casual disposable tests, recommended for persistent
personal local use, and strongly recommended for meaningful VPS data. Existing
[backup/privacy requirements](backup-restore.md) still apply: encryption at rest,
encrypted off-site transport, restricted access, retention and purge after
erasure. Private local config/policy is separate protected operator material;
do not include it in public support artifacts or assume it is stored in a dump.

## Quiesce and capture a backup

Identify the exact checkout, Compose project, image/source SHA, schema revision,
volume and selected database. Use the same explicit `-p NAME` if chosen during
installation. Keep an external operating record of erasures after each backup;
the repository does not supply this record. An older backup can contain erased
data and cannot discover later erasures by itself.

Stop all ingress and application writers/external-I/O workers, including any
enabled optional workers and setup API. Close public webhook ingress if used;
do not drop Telegram pending updates. Stop is not volume deletion:

```bash
./scripts/self-host-compose.sh --profile '*' stop
./scripts/self-host-compose.sh up -d --wait database
./scripts/self-host-compose.sh exec -T database sh -c \
  'exec psql -X -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"'
```

The expected SPEC-043 revision is `0026_conversation_feedback`. Investigate any
different/absent/multiple revision before proceeding. Ensure no other host or
process still writes this database. `pg_dump` supplies a consistent PostgreSQL
snapshot; quiescence additionally prevents new external side effects/reservations
while you choose the recovery boundary.

Choose an already provisioned encrypted storage directory outside the Docker
build context. You must verify its encryption/access yourself; these commands
do not provision an encryption system or verify a live backup destination:

```bash
umask 077
read -r -p 'Encrypted backup directory: ' backup_dir
test -d "$backup_dir"
backup_file="$backup_dir/january-$(date -u +%Y%m%dT%H%M%SZ).dump"
( set -o noclobber
  ./scripts/self-host-compose.sh exec -T database sh -c \
    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$backup_file"
)
test -s "$backup_file"
```

A failed command leaves an unverified partial file; do not call it a backup or
overwrite a known good copy. Record only opaque backup ID/time, source SHA,
head, completion, protected location and rehearsal result. Preserve operator
config/policy securely, not in Git. Size/nonzero exit is not restore credibility:
rehearse a restore into a new isolated database before depending on the copy.
`validate-backup-restore.sh` is a synthetic engineering proof, **not** a command
to run against your personal database: it seeds test rows and uses developer
Compose. Do not run repository test validators on meaningful deployment data.

## Restore into an isolated database

Keep traffic/writers stopped and the original database intact. Restore only to
a deliberately new database on your selected owned PostgreSQL service (or a
separate isolated recovery project). Review the following fixed review name;
`createdb` must fail if it already exists. No live overwrite, `--clean`, database
drop or downgrade is included:

```bash
./scripts/self-host-compose.sh exec -T -e RESTORE_DATABASE=january_restore_review \
  database sh -c 'exec createdb -U "$POSTGRES_USER" "$RESTORE_DATABASE"'
./scripts/self-host-compose.sh exec -T -e RESTORE_DATABASE=january_restore_review \
  database sh -c 'exec pg_restore --exit-on-error -U "$POSTGRES_USER" -d "$RESTORE_DATABASE"' \
  < "$backup_file"
./scripts/self-host-compose.sh exec -T -e RESTORE_DATABASE=january_restore_review \
  database sh -c 'exec psql -X -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$RESTORE_DATABASE" -c "SELECT version_num FROM alembic_version"'
```

The input is your verified protected archive from the previous section; reselect
its path explicitly in a new shell. If any step fails, leave the original
database unchanged and investigate locally. Merely restoring/reading the head
does not prove privacy/authority or authorize resume.

Before selecting the restored DB for operation, verify schema/constraints and
tenant/Assistant/connection/owner lifecycle, exact provider policies, and
attempts/reservations/counters **together** (never restore only one side to
create artificial budget headroom). Preserve inbox/update/idempotency ledgers,
completed outbound records, dead letters and ambiguous-delivery quarantine.
Reapply every post-backup subject erasure/retention deletion from the external
record through existing authorized governance operations. If that record or
the needed proof is unavailable, keep traffic stopped; the restore is not safe
to promote. Never recover content from Telegram quotes/provider bodies.

Voice bytes are bounded PostgreSQL artifacts: terminal-delivery grace is 24
hours, hard maximum retention is seven days, and privacy erasure is immediate.
Expiry/erasure is terminal even for pending delivery. Verify scoped generation/
artifact/action relationships and absent purged bytes; do not restore erased
bytes to satisfy stale work. Feedback current/history rows and their erasure
must remain consistent. See [voice](telegram-voice-tts.md) and
[feedback](conversation-feedback.md) for those exact boundaries.

Only after these checks, explicitly select the restored name in the private
`JANUARY_DATABASE_NAME`; preserve real canonical IDs/auth and cleared bootstrap
subjects. Do not rerun first-run setup to recreate authority. Recreate Redis
coordination without treating old leases/counters as business truth; durable
PostgreSQL workers reconstruct work under existing idempotency/admission rules.
Do not replay terminal/ambiguous external actions blindly.

If vector features are enabled, keep retrieval and normal index workers disabled
while starting their Qdrant dependency and rebuilding from reconciled PostgreSQL
with configured Ollama embedding provider/model/dimension. Existing explicit
operations build fresh collections and verify exact active canonical IDs before
activation:

```bash
./scripts/self-host-compose.sh --profile qdrant up -d qdrant
./scripts/self-host-compose.sh --profile polling run --rm --no-deps backend \
  python -m app.runtime.semantic_memory_operations rebuild --confirm
./scripts/self-host-compose.sh --profile polling run --rm --no-deps backend \
  python -m app.runtime.knowledge_operations rebuild --confirm
```

Run only the operation for each previously enabled feature, deliberately, after
privacy reconciliation. These perform real local embedding/index I/O and
database mutations, not canonical offline tests. A reachable model server is
required even with retrieval temporarily disabled. Inspect status/zero drift
after rebuild before re-enabling features and paired workers. Do not restore an
old vector snapshot as authority. Core-only installations need neither command
nor Qdrant. Use `--profile webhook` instead of polling for a webhook installation.

## Upgrade a pinned source installation

1. Review the proposed exact revision/release notes, compatibility, configuration
   changes and target Alembic head. The candidate creates no migration; current
   head is `0026_conversation_feedback`. A future unexpected migration requires
   a separately reviewed upgrade, not a doctor bypass.
2. Verify a protected backup and recovery/erasure record as above. Stop
   ingress/writers; retain the old source/image identity and private config.
3. With a clean deployment source tree, `git fetch origin`, then select the
   reviewed exact SHA with `git switch --detach REVIEWED_SHA`. Replace that
   placeholder deliberately; do not discard local changes or use a floating
   pull as approval. For an unpublished candidate, use its containing export;
   for an archive installation, retain the exact source SHA separately.
4. Compare the new example's **names/defaults**, not secret values; merge needed
   settings into the existing restricted file without copying over it. Keep
   canonical IDs, authentication, budgets, operator decisions and safe controls.
5. Build and run preflight against the selected code/image, with only the
   private database started:

   ```bash
   ./scripts/self-host-compose.sh --profile tools build setup-tool
   ./scripts/self-host-doctor.sh --offline --typed
   ./scripts/self-host-compose.sh --profile polling run --rm --no-deps migration alembic heads
   ./scripts/self-host-compose.sh --profile polling run --rm --no-deps migration alembic current
   ```

   Confirm one approved target head and a current revision on its reviewed
   ancestry; these read commands do not apply migrations. The current doctor
   checks this distribution's exact static head, not a future upgrade path or
   live database. Use webhook doctor/profile arguments when that mode is selected.
6. Let **one** bounded migration owner apply the reviewed target, then recreate
   workers against the same image/configuration. Do not migrate concurrently:

   ```bash
   ./scripts/self-host-compose.sh --profile polling run --rm --no-deps migration
   ./scripts/self-host-compose.sh --profile polling up -d --wait --force-recreate
   curl --fail --silent --show-error http://127.0.0.1:8000/live
   curl --fail --silent --show-error http://127.0.0.1:8000/ready
   ./scripts/self-host-compose.sh --profile polling ps
   ```

   The Compose startup migration is also bounded and idempotent at the same
   target; never run it concurrently with another migration owner. Match your
   actual host port and optional profiles. Confirm worker state, ownership,
   authority and provider admission before deliberately reopening traffic and
   performing an optional live smoke message.

Readiness/Compose wait is not a delivered-message proof. On a failure, stop
traffic, inspect closed error classes and preserve data. Prefer a forward fix or
a verified compatible application/config rollback. Do not promise DB downgrade:
governed external usage cannot be undone, and existing 0017/0025/0026 guards
protect provider, voice and feedback state. Keep the old DB/backup until the
chosen retention/privacy policy allows removal.

## Release identity

Pin an exact containing SHA until an owner-approved release tag exists.
`pyproject.toml` says `0.1.0`; that is not a published distribution guarantee.
The [changelog](../../CHANGELOG.md), [release policy](../maintainers/release-process.md)
and [release notes template](../maintainers/release-notes-template.md) establish
future version/source/Quality/configuration/migration evidence. The owner selected
[MIT](../../LICENSE) in SPEC-044; no tag, image or release is published by this
work. Historical SPEC-043 license/version observations remain unchanged.
