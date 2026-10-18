# Multi-Tenant and Assistant Administration

SPEC-030 makes PostgreSQL the canonical source of tenant, Assistant, and
platform-connection authority. This is a backend/operator model, not a
self-service organization, invitation, billing, or assistant-sharing system.

## Authority and roles

```text
ControlTenant 1 -> N Assistant 1 -> N PlatformConnection 1 -> N Conversation
Conversation 1 -> N Participant and exact-scope memory/schedule/work state
```

`tenant_owner` and `tenant_admin` manage approved tenant resource metadata;
only the owner changes tenant lifecycle. `operator` and `auditor` may inspect
content-free resource metadata, while `auditor` may also inspect audit and
governance aggregates. `viewer` receives only the tenant summary. The separate
`deployment_operator` provisions tenants and deployment-scoped provider or
governance configuration; it grants no tenant or conversation-content access.

Foreign or unknown resource identifiers return the same 404 after canonical
ownership lookup. An in-scope resource with insufficient role authority returns
403. No tenant API exposes messages, participants, memory, schedule text,
transcripts, credentials, or provider bodies.

## Provision and activate

1. Apply `0021_multi_assistant_tenancy` and confirm it is the sole Alembic head.
2. Authenticate an active deployment operator and call `POST
   /control/v1/tenants`. The transaction creates the tenant and owner membership.
3. As that owner or a tenant admin, call `POST
   /control/v1/tenants/{tenant_id}/assistants`. Supply a tenant-local slug and
   display name; the Assistant starts `disabled` with default personality state.
4. Create a connection under the same tenant and Assistant. It also starts
   `disabled`; credential values remain process-bound configuration and are not
   returned by the API.
5. Activate the Assistant, then the connection, using its exact current
   `expected_revision`. A stale revision returns 409.
6. For Telegram bootstrap, configure `JANUARY_TELEGRAM_TENANT_ID`. It may be
   omitted only when exactly one active tenant exists.

Slugs are unique only within a tenant; display names never identify authority.
Tenant ownership of an Assistant and tenant/Assistant ownership of a connection
are immutable. There is no connection rebinding workflow. Retired resources
are terminal and retained for referential history; DELETE routes are retirement
aliases rather than hard deletion.

## Disable and recovery

Disabling a tenant, Assistant, or connection fences ingress and fresh command
authorization, provider/media work, schedule enqueue/delivery, and queued
Telegram delivery. Workers re-read current lifecycle after claiming work and
before external I/O, so a claim made while active is not permission to send.
Re-enable only after the underlying configuration or incident is resolved and
use the latest revision.

Do not mutate `tenant_id` or `assistant_id` directly. Database triggers reject
authority reassignment, and composite foreign keys reject contradictory
bindings, memory scope, group ownership, and provider attribution. If migration
preflight reports contradictory ownership, leave the database at 0020, inspect
the existing authoritative signals, and resolve the data conflict through an
approved forward fix—never guess or silently merge tenants.

## Validation

Run the isolated proof before release:

```bash
./scripts/validate-multi-tenancy.sh
```

The validator owns only the `january-spec030-validation` Compose project and
ports 5444/6391 by default; override `JANUARY_SPEC030_COMPOSE_PROJECT_NAME`,
`JANUARY_DB_HOST_PORT`, and `JANUARY_REDIS_HOST_PORT` when needed. It requires
no Telegram or provider credentials and cleans only its own resources. The
proof covers populated legacy backfill, contradiction refusal, guarded and
empty downgrade paths, base/head cycles, direct constraint attacks, role and
enumeration behavior, real PostgreSQL concurrency, and zero external calls
after lifecycle disable.
