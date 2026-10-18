# Personal Context and Memory Recall Operations

This runbook covers the SPEC-027 repository candidate. It is not a production
rollout approval or compliance certification.

## Product boundary

- Personal context is explicitly authored in an exact private conversation.
- Supported keys are `preferred_name`, `preferred_language`,
  `response_preference`, `accessibility_preference`, and `personal_note`.
- No automatic extraction, inferred profile, cross-conversation identity, or
  semantic indexing of personal context exists.
- Shared explicit memory keeps its existing exact-conversation and freshly
  verified group-administrator controls.

Users inspect status and records with `/memory` and `/memory list`. They create
personal context with `/memory context add <key> <value>`, correct an owned row
with `/memory update <id> <revision> <content>`, delete it with `/memory delete
<id> <revision>`, and clear their exact-conversation records with `/memory
clear_mine confirm`. `/memory recall off` immediately removes memory and
personal context from responses for that participant; `/memory recall on`
restores eligible canonical recall but cannot restore deleted content.

## Deployment and migration

Apply migration `0018_user_controlled_memory` only after 0017. Before rollout,
run `./scripts/validate-personal-context.sh`; it proves the 0017 → 0018 → 0017
→ 0018 lifecycle on empty state, the downgrade refusal after governed state,
integration behavior, retention runtime, and base/head lifecycle.

In a sandbox with an already-confirmed Docker denial, use
`./scripts/validate-personal-context.sh --repository-only` for focused tests
without retrying Docker. This mode deliberately exits 2 after successful tests
and reports integration/migration/runtime proof pending; it is not a release
gate pass. The default invocation still requires every Docker-backed phase.

Migration preflight refuses cross-conversation creator references. Downgrade
refuses any personal-context, recall-policy, or memory-control-operation state.
Do not delete those rows to force a rollback. Roll back the application only
to a binary that tolerates migration 0018, or restore from a reconciled backup
under the backup runbook.

## Runtime checks

The Telegram command worker owns management commands. The existing retention
worker clears expired canonical content in deterministic configured batches.
The semantic-memory worker handles explicit-fact UPSERT/DELETE intents only.
No new worker or provider pipeline exists.

Check only bounded, content-free telemetry:

- `january_memory_control_operations_total` by closed operation, outcome,
  record kind, and conversation type;
- existing semantic index/query fallback counters;
- existing retention worker operation and duration metrics.

Never place memory values, previews, participant IDs, Telegram IDs, command
arguments, prompts, vectors, or public record IDs in metric labels or operator
logs.

## Incident response

If private context appears outside its owner/private conversation, disable the
affected command/planning workers, preserve content-free evidence, and treat it
as a privacy incident. Verify PostgreSQL ownership, kind/visibility/scope,
recall policy, and `memory_privacy_revision`; do not inspect content unless the
incident authority explicitly permits it.

If Qdrant contains a personal-context ID, stop semantic workers, remove the
derived point, verify all indexing queries require `explicit_fact`, and rebuild
from reconciled PostgreSQL authority. A stale vector never authorizes recall.

If clear is interrupted, replay the same durable command job. Its operation row
resumes bounded batches and prevents duplicate durable effects. Do not create a
replacement command identity merely to bypass an in-progress operation.

## Backup and external ownership

Live deletion/expiry is authoritative, but older backups or delivered Telegram
messages may retain copies. Follow `docs/runbooks/backup-restore.md`; backup
purge/reapply policy, content-free audit retention, and production acceptance
remain operating-owner decisions.
