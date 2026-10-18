# SPEC-030 — Multi-Assistant / Multi-Tenant Product Model

Date: 2026-09-11

Status: **APPROVED PRODUCT SPEC**. The Product Owner's SPEC-030 end-to-end
goal authorizes the bounded design, implementation, and validation described
here. It is not production rollout, billing, legal, or compliance approval.

SPEC-029 is the completed predecessor. SPEC-014 remains
`DEFERRED / BLOCKED_ON_EXTERNAL_PREREQUISITE`; this work does not reopen it,
implement Zalo, or begin SPEC-031.

## Purpose

Turn Lumi's partial tenant and Assistant concepts into one canonical,
fail-closed ownership model supporting multiple mutually isolated tenants and
multiple independently configured assistants per tenant. Existing security,
privacy, explicit-memory, provider-governance, scheduling, delivery ambiguity,
and deployment-authority boundaries remain authoritative.

## Existing-model audit

The repository already has a durable tenant primitive and role system:

- `control_tenants` is the durable administrative/security boundary.
- `control_operator_memberships` assigns `tenant_owner`, `tenant_admin`,
  `operator`, `auditor`, or `viewer` to an external `(issuer, subject)` identity.
- `control_deployment_authorities` separately grants `deployment_operator`.
- `assistants` has a stable UUID, display name and active/disabled state but no
  canonical tenant column, tenant-local slug, or revision.
- `platform_connections` belongs to exactly one Assistant and has a globally
  unique `(platform, external_bot_id)`, but no constrained tenant column.
- `conversations` belongs to exactly one PlatformConnection; `participants`
  are unique only within one conversation.
- `control_assistant_bindings` and `control_connection_bindings` duplicate
  tenant attribution. They are individually unique by resource after SPEC-026,
  but no database constraint proves that a connection binding agrees with its
  Assistant binding.
- `control_group_bindings` carries another tenant copy with no cross-table
  consistency constraint.
- memory rows deliberately duplicate Assistant, connection and conversation
  IDs for exact-scope reads, but independent foreign keys permit contradictory
  combinations through direct normal schema use.
- schedules and occurrences bind participant plus conversation and therefore
  derive connection, Assistant and tenant indirectly.
- provider routing, budget, snapshot, and usage rows carry tenant plus resource
  IDs. Shape checks exist, but the database does not prove that those IDs share
  ownership. Runtime source resolution currently obtains tenant through the
  optional control-connection binding.
- governance subject/group operations remain conversation/participant scoped;
  deployment export is tenant-independent and requires `deployment_operator`.
- bootstrap can create an Assistant and connection without any tenant binding,
  a latent single-assistant/deployment assumption.
- control-plane resource authorization relies on a requested tenant plus a
  mirror binding lookup. Main control-plane cross-tenant behavior has limited
  direct proof; provider-control tests cover some foreign-scope denial.

The current logical graph is:

```text
ControlTenant 1 ── N ControlOperatorMembership N ── 1 OperatorIdentity
ControlTenant 1 ── N ControlAssistantBinding N ── 1 Assistant
ControlTenant 1 ── N ControlConnectionBinding N ── 1 PlatformConnection
Assistant     1 ── N PlatformConnection
PlatformConnection 1 ── N Conversation
Conversation  1 ── N Participant
Conversation  1 ── N Memory / Schedule / Message / Work records
```

The two control bindings are presently an unconstrained parallel authority
graph. SPEC-030 makes the core resource rows authoritative and retains those
tables only as constraint-backed compatibility indexes while existing APIs and
older integrations transition.

## Product decisions

### Tenant definition and lifecycle

A tenant is the durable administrative and security boundary owning
assistants, platform connections, tenant-scoped configuration, provider
resource governance, content-safe audit metadata, and tenant-scoped operational
authority. It is not a Telegram user, group, conversation, Assistant, provider,
or billing account.

`control_tenants` is the existing correct durable primitive and is reused; no
Organization, Workspace, AssistantTenant, or second membership system is added.
Its public UUID is stable. Its globally unique slug remains an administrative
lookup/display field for compatibility, not authorization identity. Name is
mutable under optimistic revision. Lifecycle is `active`, `disabled`, or
`retired`; retired is terminal. Tenants are not hard-deleted in SPEC-030.

A disabled or retired tenant blocks new ingress processing, provider I/O,
scheduled enqueue, and outbound external I/O through its descendants. Read-only
authorized metadata remains inspectable. Re-enabling a disabled tenant is an
explicit owner action; retired tenants cannot be re-enabled.

Tenant creation is deployment provisioning, not self-service signup. It
requires current `deployment_operator` authority. The creator receives an
explicit `tenant_owner` membership as part of the same transaction; deployment
authority alone never grants later tenant access or content visibility.

### Assistant ownership, identity and lifecycle

Every Assistant belongs to exactly one tenant for its entire lifetime. Its UUID
is stable public identity. `name` is a mutable display value only. `slug` is a
mutable administrative identifier unique within its tenant and never used as
authorization proof. Display-name equality across or within tenants has no
identity effect.

Assistant lifecycle is `active`, `disabled`, or `retired`; retired is terminal.
Mutable metadata and lifecycle use a positive optimistic `revision`. New
assistants are created disabled and receive the existing safe default
personality/configuration before they may be explicitly enabled. Assistants are
disabled or retired, never hard-deleted. Cross-tenant reassignment is not
supported.

One tenant may own many assistants. Each Assistant has independent personality
and configuration revisions, connections, conversations, participants,
memory/context, schedules, status, and resource-scoped provider governance.
Tenant administration of more than one Assistant never grants one Assistant's
runtime access to another Assistant's private content.

### PlatformConnection ownership and binding

Every PlatformConnection belongs to exactly one tenant and exactly one
Assistant in that tenant. The persisted `(tenant_id, assistant_id)` pair is
database-constrained to the canonical Assistant owner. `(platform,
external_bot_id)` remains deployment-global unique because it is the inbound
routing identity: one incoming Telegram bot update has exactly one canonical
connection and therefore one Assistant and tenant.

Connection lifecycle is `active`, `disabled`, `error`, or `retired`; retired is
terminal. `error` remains a recoverable operational state. New connections are
created disabled. Enabling requires an active tenant and Assistant. Connection
authority fields are immutable. Cross-tenant reassignment is unsupported and
within-tenant rebinding is unsupported in v1, including unused connections;
administrators create a new connection instead. No conversation history is
silently retargeted.

### Conversation and participant scope

A Conversation belongs to one PlatformConnection and derives exactly one
Assistant and tenant from the constrained persisted connection. SPEC-030 does
not add redundant authority columns to conversations. Incoming payload IDs
cannot override this path. Outbound work continues to carry a conversation
reference and re-resolves the current canonical connection/Assistant/tenant
before external I/O.

A Participant is unique within one conversation. The same Telegram/platform
user interacting with another conversation or Assistant creates an independent
Participant, preferences, consent, personal context, and schedule scope. No
cross-conversation, cross-assistant, cross-tenant, or global-human identity
federation is introduced. SPEC-025 erasure matching is a cleanup mechanism, not
identity federation, and its existing PlatformConnection boundary remains.

### Memory isolation

SPEC-027 remains exact Assistant + PlatformConnection + conversation +
participant scope. Explicit facts are same-conversation; personal context is
creator-private and exact-private-conversation. Database constraints must prove
that duplicated memory/recall scope IDs form one canonical chain. Assistant B
cannot retrieve Assistant A memory, including when both share a tenant.

Qdrant stays derived and contains opaque exact-scope metadata. Queries filter
Assistant, connection and conversation, and PostgreSQL revalidation must prove
the same canonical chain before text enters context. There is no cross-assistant
semantic recall and no cross-tenant Qdrant retrieval.

### Scheduling isolation

Schedules remain creator-participant plus exact-conversation records. Their
Assistant and tenant derive through the immutable conversation → connection →
Assistant path. Neither Assistant nor connection rebinding is supported, so an
existing schedule cannot be retargeted. Disabled/retired tenant, Assistant or
connection state suppresses enqueue and blocks outbound external I/O. A stale
worker revalidates at the pre-I/O boundary and makes zero Telegram calls.

### Control-plane roles and content authority

The existing role system is authoritative; no second membership entity is
added.

- `tenant_owner`: tenant metadata/lifecycle and all tenant resource metadata;
  membership authority remains as SPEC-021 defines.
- `tenant_admin`: create and manage Assistants/connections and their approved
  metadata/configuration; cannot retire a tenant or manage deployment scope.
- `operator`: no resource mutation unless a future explicit resource-grant
  model is implemented. Because no such durable grant exists today, it fails
  closed in SPEC-030.
- `auditor`: content-free tenant/resource configuration, governance aggregate,
  and audit reads only.
- `viewer`: minimum tenant summary only; no provider usage/cost or content.
- `deployment_operator`: deployment provisioning/provider/governance authority
  only. It is not tenant membership and confers no conversation, memory,
  schedule, participant, or tenant audit access.

Private conversation content, memory, personal context, transcripts, and
schedule content are not exposed through tenant administration. Protected
resource lookup uses persisted ownership then authorization; foreign and unknown
resource IDs return deterministic `404 not_found_or_forbidden` after the caller's
tenant membership is established. A caller without tenant membership receives
the same non-enumerating 404. Authenticated but underprivileged members receive
403 only for an operation on an in-scope resource they are allowed to know.

### Provider governance

SPEC-026's only budget scopes remain deployment, Assistant, and
PlatformConnection. SPEC-030 adds no tenant budget and no billing semantics.
Assistant and connection policies/budgets must use the canonical resource
tenant, and database constraints reject foreign `(tenant, resource)` pairs.
Usage and work snapshots retain their canonical opaque attribution. Unknown,
partial, invalid and ambiguous usage remain distinct and never become zero.

### Privacy, export and erasure

SPEC-025 scopes remain subject, group, and deployment. Tenant administration
does not become a content export bypass. Subject export remains exact
conversation/participant and excludes other assistants' or tenants' content.
Group export remains current group authorized. Deployment export remains
content-free and tenant-independent. Erasure continues across the existing
Assistant/PlatformConnection cleanup boundary without creating a federated
subject identity. Constraints prevent erasure from orphaning contradictory
ownership.

### Audit, observability and safety

Audit events may contain approved opaque internal tenant/Assistant/connection
references plus closed action/outcome codes, never content or credentials.
Metrics may use only closed categories such as resource kind, lifecycle state,
authorization outcome or routing result. Tenant, Assistant, connection,
conversation, participant, Telegram/user IDs, names, slugs, usernames and
content are prohibited metric labels.

New assistants and connections fail closed as disabled. Enabling is explicit
and cannot bypass required default personality, safety, provider, rate,
concurrency, privacy, or delivery gates.

## Legacy migration and bootstrap

Migration `0021_multi_assistant_tenancy` preserves every existing explicit
tenant binding. It performs preflight consistency checks before enforcing the
new graph:

1. Reject contradictory Assistant/connection/group/provider ownership rather
   than guessing or reparenting.
2. Reuse each Assistant's single existing control binding where present.
3. Place only previously unbound legacy Assistants into one reserved
   `legacy-default` tenant representing the repository's former deployment-wide
   administrative boundary. Existing tenant identifiers are never merged.
4. Backfill connection tenant strictly from its Assistant.
5. Backfill missing compatibility binding rows from canonical core ownership,
   never the reverse.
6. Give legacy Assistants deterministic opaque tenant-local slugs and revision
   1; preserve names/status. Give legacy tenants/connections revision 1 and
   preserve lifecycle/status.
7. Validate memory, recall, provider and group scope chains, then add constraints.

The reserved legacy tenant has a fixed schema-owned UUID/slug. A conflicting
pre-existing reserved identity causes migration refusal. Fresh empty installs
receive that one disabled-by-default provisioning boundary for bootstrap
compatibility; operators may instead configure an explicit tenant UUID.

Bootstrap resolves an existing configured connection first. New connection
creation uses the explicitly configured tenant; if omitted, exactly one active
tenant may be selected for legacy compatibility. Zero or multiple candidates
fail closed. Assistant lookup is tenant-local, never deployment-global by name.

Downgrade is allowed only when no SPEC-030-specific tenant/resource state would
be discarded or made ambiguous. Otherwise it fails with the exact SPEC-030
guard and leaves revision 0021 current.

## Security invariants

1. Every Assistant resolves to exactly one tenant.
2. Every PlatformConnection resolves to exactly one tenant and one approved
   Assistant binding in that tenant.
3. Every Conversation resolves to exactly one Assistant and tenant through
   canonical persisted relationships.
4. No tenant/resource identifier from request, update, queue, or job payload can
   override persisted authority.
5. Normal database use cannot create a foreign tenant/resource combination in
   control bindings, provider scopes, group bindings, or duplicated memory scope.
6. Memory retrieval cannot cross exact approved Assistant/conversation scope.
7. Schedules cannot execute under a different Assistant/connection from their
   conversation owner.
8. Disabled/retired tenants or assistants and disabled/retired/error connections
   cannot perform provider or proactive external work.
9. Provider governance resolves resource scopes through canonical ownership and
   keeps all existing cumulative admission rules.
10. Deployment operational authority is not tenant membership or tenant-content
    authority.

## Minimum control-plane surface

SPEC-030 completes only bounded metadata/lifecycle operations under the existing
`/control/v1` convention:

- provision/list/get/update tenant metadata and lifecycle under the role rules;
- create/list/get/update/disable/retire Assistants within an authorized tenant;
- create/list/get/update/disable/retire connections within an authorized tenant;
- inspect canonical tenant/Assistant/connection ownership and revisions.

There is no generic CRUD, hard delete, content browser, invitation UI, billing,
or secret-value read endpoint. Request `tenant_id` scopes authorization but
never overrides the resource's persisted owner.

## Acceptance criteria

1. Schema and direct-insert attacks prove exact tenant/Assistant/connection,
   group, memory, recall and provider-scope consistency.
2. A live PostgreSQL legacy fixture with multiple tenants, Assistants,
   connections, conversations, memory, schedules and provider records upgrades
   without ownership change; contradictory fixtures are refused.
3. Tenant A has A1/A2 and Tenant B has B1, each with connection, private
   conversation and participant; same names do not affect identity.
4. A1 cannot read/mutate A2 private state through runtime or admin surfaces;
   A1/A2 cannot access B1; Tenant A administrators cannot use Tenant B IDs.
5. Control-plane owner/admin/operator/auditor/viewer/deployment-operator,
   unknown, malformed, disabled and foreign-resource outcomes match the exact
   role and 403/404 contract.
6. Concurrent same-tenant slug creation yields exactly one success; revision
   compare-and-swap prevents lost lifecycle/metadata updates; cross-tenant
   binding attempts fail.
7. Telegram ingress derives one canonical connection/Assistant/tenant and
   rejects unknown or inactive authority before normal processing.
8. Planning/provider and outbound workers revalidate current tenant, Assistant
   and connection lifecycle immediately before external I/O.
9. A worker claim followed by disable produces zero provider/Telegram adapter
   calls and a deterministic suppressed/retry-safe result.
10. Exact-scope deterministic and semantic memory proof rejects A1/A2 and
    Tenant A/B substitution, including stale Qdrant candidates.
11. Scheduling proof shows an A1 schedule cannot execute through A2/B1 and an
    inactive ancestor prevents send.
12. Provider policy/budget/usage proof rejects foreign resource scope while
    preserving unknown usage and non-billing language.
13. Subject/group/deployment export and erasure proof shows no new cross-tenant
    or cross-assistant disclosure.
14. Metrics/audit review proves no high-cardinality identity/content labels.
15. Alembic and dedicated validator prove one head, 0020→0021, guarded
    0021→0020, empty reversible lifecycle, base/head lifecycle, populated legacy
    upgrade, clean-runner `uv` resolution, isolated Docker resources and cleanup.
16. General and every affected validator pass without skips, xfails, broad
    status assertions, sequential race substitutes or masked failures.

## Explicit out of scope

Billing, invoices, subscriptions, monetization, self-service signup,
organization UI, invitations/email identity, SSO/SCIM, assistant marketplace or
sharing, cross-assistant memory/conversation transfer, Assistant orchestration,
multi-agent routing, one Telegram bot impersonating multiple assistants,
generic platform federation, Zalo, SPEC-031, external calendar/email, and
unrestricted agent workflows.

## External prerequisites

Production tenant names/slugs, identity-provider operation, membership review,
provider routes/prices/budgets, retention, backup purge/reapply, alert routing,
credential provisioning, and rollout remain operating-owner decisions. They do
not change repository mechanism completion and cannot be inferred from fixtures.

