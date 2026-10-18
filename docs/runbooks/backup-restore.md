# Backup And Restore

Backups are operator-managed copies for recovery (SPEC-020/SPEC-025 FR-09).
They must be encrypted at rest, and any off-site copy must use encrypted
transport (SPEC-025 FR-10). Backups taken before an erasure may contain the
erased data; the operating owner must purge such copies under the declared
backup-retention and purge policy. Tombstones present in a backup remain
authoritative after restore, but a backup taken before a later erasure cannot
contain that later tombstone. Never promote such a restore until every
post-backup erasure has been reapplied from an external operating record and
verified. This repository does not maintain that external record; its
availability, retention, and reconciliation are operating-owner controls.

PostgreSQL is authoritative. Redis streams, rate-limit counters, and provider
concurrency leases are reconstructible coordination state and are not restored
as business truth.

SPEC-026 provider registry, route, health, price, budget, usage-quality,
estimate, and reservation records are PostgreSQL-authoritative operating state.
Restore attempts, reservations, and counters together; restoring only one side
can create false budget headroom. Cost fields remain estimates, not billing
truth. After governed provider I/O, do not downgrade away migration 0017;
externally incurred usage cannot be reversed by an older binary or restore.

SPEC-019 semantic-index jobs are also PostgreSQL data. Qdrant vectors are
privacy-sensitive derived data, not anonymous data and not backup authority.
After PostgreSQL restore and post-backup erasure reconciliation, an empty
Qdrant instance can be rebuilt by scheduling an explicit-memory backfill.
Reconciliation must remove points for canonical deleted/inactive memories;
workers and the derived index remain stopped until this proof is complete.

SPEC-027 personal-context content, optimistic revisions, exact-conversation
recall policies, and content-free mutation operations are PostgreSQL authority.
Restore them atomically with participants, conversations, memory items, and
privacy revisions. Before workers start, reapply post-backup erasure/expiry
tombstones, verify personal-context rows are creator-only/private-conversation,
and verify Qdrant contains explicit facts only. Recall-off and deleted/expired
canonical state remain authoritative after restore; a vector or older backup
must never re-enable or recreate content.

In an isolated environment, apply migration head, seed synthetic data, run
`pg_dump`, restore into an empty database, then verify migration head, row and
relationship counts, idempotency keys, redaction tombstones, completed outbound
actions, recovery disposition, pending schedule, and summary-content redaction.
Summary text is derived content and must never be included in operator reports.
Start synthetic workers
after restore. Never use production payloads in this rehearsal; delete temporary
dumps or keep them only in ignored local storage.

Run `./scripts/validate-backup-restore.sh` for the local synthetic rehearsal.
