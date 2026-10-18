# SPEC-030 Design Handoff

Date: 2026-09-11

## Status

**APPROVED DESIGN — IMPLEMENTATION AUTHORIZED**

This design implements the approved SPEC-030 product contract. It creates no
parallel tenant or role system and does not authorize SPEC-031 or Zalo.

## Canonical authority graph

```text
ControlTenant (canonical Tenant) 1 ── N Assistant
Assistant                         1 ── N PlatformConnection
PlatformConnection                1 ── N Conversation
Conversation                      1 ── N Participant
Conversation/Participant          1 ── N exact-scope Memory and Schedule state

OperatorIdentity 1 ── N OperatorMembership N ── 1 ControlTenant
OperatorIdentity 1 ── N DeploymentAuthority (tenant-independent)

ControlAssistantBinding / ControlConnectionBinding
  compatibility indexes constrained to the canonical core ownership above
```

Provider policy, budget, snapshot and usage rows may retain denormalized opaque
tenant/resource attribution only under composite foreign keys to this graph.
Conversation tenant and Assistant are derived, not duplicated.

## Entity design

| Entity | Authoritative owner / cardinality | Keys and uniqueness | Lifecycle / mutable fields | Immutable authority / authorization path |
| --- | --- | --- | --- | --- |
| `control_tenants` | deployment-provisioned security boundary | UUID; deployment-global unique slug | name, status, revision; active/disabled/retired | UUID immutable; create requires deployment authority, later access requires membership |
| `assistants` | exactly one tenant; tenant 1:N assistants | UUID; unique `(tenant_id, slug)` and `(id, tenant_id)` | name, slug, status, revision; active/disabled/retired | tenant immutable; resource lookup by `(id, tenant_id)` after membership |
| `platform_connections` | exactly one Assistant in same tenant; Assistant 1:N | global `(platform, external_bot_id)`; unique `(id, tenant_id)` and `(id, assistant_id)` | credential reference, configuration, status, revision; active/disabled/error/retired | tenant and Assistant immutable; composite FK to Assistant; request path never selects owner |
| `conversations` | exactly one PlatformConnection | existing `(platform_connection_id, platform_conversation_id)` plus `(id, platform_connection_id)` | existing title/status/settings/config pointer | connection immutable; Assistant/tenant derive by joins |
| `participants` | exactly one Conversation | existing `(conversation_id, platform_user_id)` and `(id, conversation_id)` | exact-conversation preferences/membership/privacy | conversation immutable; platform ID is not global identity |
| memory/recall | exact participant/conversation/connection/Assistant | existing public/command/revision uniqueness | existing content/status/revision/recall | composite FKs prove duplicated scope chain; no tenant column added |
| schedules/occurrences | exact participant/conversation | existing public/source/date uniqueness | existing schedule lifecycle | conversation path resolves immutable connection/Assistant/tenant |
| provider scopes | deployment or exact Assistant/connection | existing scope keys and revision uniqueness | immutable revisions/current heads | composite tenant/resource FK; runtime attribution comes from core rows |
| control compatibility bindings | canonical resource tenant only | existing one row per Assistant/connection | none | composite FK makes divergence impossible; never used as the root authority |
| group bindings | exact connection tenant | existing tenant/connection/external group | settings/revision | composite FK to connection tenant |

## Migration 0021 design

`0021_multi_assistant_tenancy` has `down_revision =
0020_proactive_scheduling` and preserves the central Alembic VARCHAR(64)
bootstrap behavior.

Expand/backfill/validate/constrain sequence:

1. Add nullable revision/slug/tenant fields and required supporting unique keys.
2. Preflight duplicate/reserved identity and all currently expressible
   contradictions: Assistant vs connection bindings, group binding vs connection,
   memory/recall Assistant-connection-conversation, provider tenant-resource and
   source attribution.
3. Create/reuse only the reserved legacy tenant under the exact product rules.
4. Backfill Assistant tenant from its unique binding or the legacy boundary;
   backfill deterministic opaque slugs and revision 1.
5. Backfill connection tenant from Assistant and revision 1. Fill missing
   compatibility rows from canonical ownership.
6. Backfill tenant revision and validate lifecycle values.
7. Add non-null, check, scoped uniqueness, composite foreign keys, and
   authority-reassignment triggers only after the data passes.

Downgrade first checks for any non-legacy tenant, any resource no longer
representable by pre-0021 semantics, retired lifecycle, or revision/slug state
whose removal would lose a durable effect. It raises exactly
`SPEC-030 tenancy state blocks downgrade` and leaves 0021 current. Validator-
owned state is removed through normal DELETE only for the empty downgrade proof.

## Application authority resolution

Add one database authority module with resource loaders and current-state
checks. The sequence is:

```text
authenticate actor
→ establish tenant membership (or explicit deployment authority for provision)
→ load resource by canonical persisted `(tenant_id, resource_id)` relationship
→ evaluate role and lifecycle
→ mutate/read in the same transaction
```

Ingress/job payload resolution starts from the persisted connection or
conversation and derives tenant; it never begins with payload tenant. Provider
work source uses `PlatformConnection.tenant_id`, not an optional control mirror.
All external-I/O workers call the fresh lifecycle resolver after claim and
immediately before their adapter call.

## Lifecycle transitions

```text
active <──> disabled ──> retired
active ────────────────> retired
retired ──X──> any other state
```

Connection `error` may transition to disabled or active after explicit repair;
retired remains terminal. A tenant/Assistant must be active before a connection
may become active. New Assistants and connections start disabled. Legacy active
rows remain active after migration.

An inactive ancestor yields: ingress rejection/no normal processing; no new
provider I/O; schedule suppression before enqueue where available; outbound
skip before Telegram; no queued content retargeting. Claimed work is not proof
of current permission.

## Control-plane contract

- POST tenant: `deployment_operator`; transaction creates explicit owner membership.
- GET tenant summary: any active membership.
- PATCH tenant name: owner/admin with expected revision; lifecycle disable/enable
  requires owner; retire requires owner and confirmation semantics already
  represented by deliberate status payload plus audit.
- Assistant/connection list/get: active member roles receive metadata only.
- Assistant/connection create: owner/admin; starts disabled.
- Metadata patch: owner/admin, expected revision.
- Lifecycle patch/DELETE alias: owner/admin; terminal transition rules.
- `operator` is denied resource writes because no explicit resource grant table
  exists. Auditor is read-only; viewer has tenant summary/minimum metadata only.
- Foreign/no-membership/unknown resource: deterministic 404. Known in-scope but
  insufficient capability: 403. Malformed UUID/input: deterministic 422.

The API never returns credential values, content, memory, transcript, participant
identity, or schedule content. Slug/name are presentation fields, not auth keys.

## Required security invariants

The ten numbered invariants in the Product Spec are design gates. Their primary
proof is respectively: non-null/composite schema constraints; resource loader
queries; conversation FK path; payload substitution tests; direct invalid SQL;
memory deterministic/semantic negative tests; schedule/outbound binding tests;
instrumented stale-worker tests; provider scope/attribution tests; and separate
deployment/membership authorization tests.

## Query isolation review targets

- `interface/http/control_plane.py`: remove binding-rooted resource lookups.
- `interface/http/provider_governance_control.py`: authorize through core tenant.
- `infrastructure/database/provider_governance.py`: source tenant from connection
  and verify core `(tenant, Assistant, connection)` atomically.
- `infrastructure/database/memory.py` and `semantic_memory.py`: retain exact
  filters; rely additionally on schema chain constraints.
- `infrastructure/database/scheduling.py`, planning and outbound runtimes: add
  tenant ancestor to fresh lifecycle checks.
- bootstrap: explicit/single-tenant resolution only; no global name search.

An opaque UUID is never authorization.

## Concurrency design

- Assistant slug uniqueness is database-backed; simultaneous creates in separate
  PostgreSQL transactions yield one durable row and one deterministic conflict.
- Assistant/connection/tenant patches use `UPDATE ... WHERE revision = expected`
  or locked equivalent and increment once; concurrent stale writes yield 409.
- Authority fields are absent from patches; database triggers reject Assistant
  tenant mutation and connection tenant/Assistant rebinding, while composite
  constraints reject cross-tenant combinations.
- Existing provider reservations and schedule claims retain their real
  concurrency tests; new lifecycle-vs-I/O proof uses two transactions/events,
  not sequential substitution or sleeps.

## Validation map

- Unit: identity/slug validation, lifecycle transitions, request schemas,
  privacy-safe response bodies, resolver decisions and disabled behavior.
- Live PostgreSQL: migration/backfill, constraint attacks, complete isolation
  matrix, CAS and create races, control-plane authorization, memory/schedule/
  provider/governance integration.
- Runtime: deterministic ingress routing and instrumented provider/Telegram zero
  calls after disable between claim and pre-I/O revalidation.
- Migration: heads; 0020→0021; populated legacy upgrade; contradictory refusal;
  guarded populated downgrade; validator-owned cleanup; empty
  0021→0020→0021; base→head→base→head.
- Static/integrity: changed-query scope review, prohibited metric labels,
  skip/xfail/broad 403-or-404/`|| true`/broad exception/sleep/manual ALTER review,
  executable/LF/shebang, shallow checkout, PATH and repository-local uv.
- Full matrix: canonical, SPEC-030, provider governance, governance, memory,
  commands, safety, reliability, observability, deployment, proactive scheduling,
  and Telegram media validators.

## Recovery

The implementation is additive and uncommitted. Before migration deployment,
application rollback is a patch revert. After deployment, old binaries are
compatible only during the documented expand window; production routine
downgrade is not implied. A contradictory preflight changes no ownership. A
failed migration is forward-fixed or restored according to SPEC-020; it never
uses manual ALTER or silent reparenting.
