# SPEC-021 Authenticated Operator and Group Administration Control Plane

## Status

Product specification prepared from the accepted Phase 6 administration
dashboard roadmap and the completed SPEC-020 deployment handoff. This document
authorizes product design only. It authorizes no runtime implementation, test
change, migration, ADR, runbook, commit, or push.

SPEC-020 remains the latest completed implementation. SPEC-014 remains
deferred behind the external Zalo prerequisite. SPEC-021 does not begin
SPEC-022 or introduce Zalo runtime behavior.

Retrospective bounded extension (2026-09-02): the Product Owner's SPEC-025
final authorization reuses the implemented `(issuer, subject)` identity and JWT
authentication boundary while adding an explicit tenant-independent
`deployment_operator` grant for SPEC-025 FR-04 only. This is not a tenant role:
tenant membership never implies it, and it never confers tenant access. The
extension, migration, and governance endpoint are authoritative in SPEC-025 and
ADR-0022; the historical design status above is not authority to disable them.

## Outcome

An authenticated operator can safely manage assistants, Telegram platform
connections, groups, group configuration, personalities, stickers, operational
status, and audit history through a provider-neutral control-plane API suitable
for a web administration client and a compatible operator CLI.

The control plane applies explicit tenant and resource authorization, preserves
immutable configuration history, rejects stale concurrent edits, never returns
secrets, and keeps existing Telegram administrator commands compatible. A
control-plane operator is not silently granted Telegram group authority merely
by signing in.

## Objectives

- Authenticate human operators through an approved external identity boundary.
- Represent assistants, platform connections, groups, memberships, roles, and
  configuration revisions as explicitly scoped control-plane resources.
- Provide least-privilege authorization for tenant, assistant, connection, and
  group administration.
- Expose a stable API for a future web dashboard and operator CLI without
  coupling either client directly to the database.
- Preserve existing Telegram command authorization and group-level policy.
- Make every sensitive administrative mutation auditable without storing
  message content, prompts, credentials, or provider bodies in audit records.
- Prevent cross-tenant leakage, privilege escalation, stale overwrites,
  duplicate durable effects, and secret disclosure.
- Support safe recovery, revision inspection, and rollback of control-plane
  configuration.

## Non-goals

- Implementing runtime code, frontend code, migrations, ADRs, or runbooks in
  this product-specification task.
- Selecting a cloud identity provider, OIDC vendor, session store, hosting
  platform, or secret manager.
- Replacing Telegram administrator commands or changing their existing
  authorization contract.
- Implementing billing, usage-based plans, tenant provisioning automation,
  multi-region control-plane replication, or general-purpose SaaS onboarding.
- Exposing raw Telegram bot tokens, provider keys, database credentials,
  webhook secrets, private keys, prompts, messages, memories, vectors, or
  provider request/response bodies.
- Granting a control-plane operator access to conversation content by default.
- Automatically linking a control-plane identity to a Telegram participant.
- Automatically mutating Telegram webhooks at API startup.
- Adding new Telegram media, voice, scheduled messaging, Zalo, or provider
  routing behavior.
- Bypassing safety, retention, consent, rate-limit, semantic-memory, summary,
  delivery-ambiguity, or deployment boundaries.

## Scope

In scope are authenticated control-plane sessions, tenant and operator
membership, assistant and connection administration, group inventory and
configuration, personality and sticker management, operational status views,
immutable revisions, audit events, API contracts, CLI compatibility,
authorization failures, recovery behavior, and validation requirements.

Existing product behavior remains authoritative:

- PostgreSQL remains canonical for durable product and control-plane state.
- Telegram commands continue to obtain fresh current group authorization
  through the platform adapter for protected group changes.
- Group configuration remains versioned and applies only at the documented
  configuration boundary; a control-plane edit does not rewrite historical
  response or personality snapshots.
- Memory, summaries, semantic retrieval, retention, safety, ambient behavior,
  rate limits, outbound idempotency, and ambiguous delivery remain unchanged.
- Operational telemetry remains content-safe.

## Architecture impact

SPEC-021 adds a control-plane boundary around the existing modular monolith;
it does not replace the Telegram runtime or create a second business domain.

    authenticated operator or CLI
                |
          control-plane API
                |
        authorization + revisions + audit
                |
          PostgreSQL canonical state
                |
    existing assistant / Telegram runtime

The control-plane API may share the existing process boundary initially, but
its routes, authentication middleware, resource authorization, and audit
service must remain explicit. A future deployment may place it behind a
separate ingress or process without changing the domain contract.

The control plane may enqueue bounded asynchronous work for approved platform
operations. It must not hold a database transaction, row lock, or ordering lock
across Telegram, provider, secret-manager, or other external I/O. The API must
not become a hidden worker supervisor or a second source of truth.

## Domain model

The following are logical product entities. Physical tables and identifiers are
implementation choices for a later phase.

### Tenant

An isolation boundary for operators, assistants, platform connections, groups,
configuration, audit records, and operational metadata. Every tenant-owned
resource carries an immutable tenant identity. A request may address only
resources within the authenticated operator's tenant grants.

### Operator identity

An external identity represented by a stable `(issuer, subject)` pair plus
minimal display metadata. The system stores no upstream password. An identity
may be disabled, required to reauthenticate, or removed without deleting
tenant-owned product state.

### Operator membership

The relationship between an operator identity and a tenant, including role,
scope, status, grant/revocation timestamps, and the actor that changed it.
Membership is deny-by-default and is evaluated on every protected request.

### Assistant

A tenant-scoped logical assistant with a display name, lifecycle status, and
references to its immutable configuration resources. An assistant cannot be
read or changed through an unrelated tenant or connection.

### Platform connection

A tenant-scoped connection to a Telegram bot or another already-supported
platform identity. It contains non-secret metadata, capability state, delivery
mode, and external identity references. Secret values are represented only by
external secret references and redacted status.

### Group binding

A durable association between a platform connection, assistant, and Telegram
group or private conversation scope. The binding defines whether the assistant
is enabled and which tenant owns the relationship. A Telegram chat ID alone is
not a cross-tenant authorization proof.

### Group configuration revision

An immutable version of group behavior, including references to personality,
sticker, participation, safety-compatible, and response-frequency settings.
Each revision records its creator, creation time, parent revision, effective
state, and content-free change summary. Existing response snapshots remain
bound to the revision selected when they were created.

### Audit event

A content-safe record of an authentication, authorization, membership,
configuration, secret-reference, connection, or recovery action. It includes
actor, tenant, resource type and identifier, action, outcome, request/correlation
reference, timestamp, and reason code where applicable. It excludes message
content, prompts, memories, vectors, credentials, tokens, and provider bodies.

## Authorization model

Authorization is deny-by-default, server-side, resource-scoped, and evaluated
after authentication. Client-side route visibility is never a security
boundary.

### Roles

- `tenant_owner`: full tenant administration, including membership and
  ownership transfer, subject to step-up authentication and recovery controls.
- `tenant_admin`: manage assistants, connections, groups, configuration,
  operational views, and audit reads; cannot transfer ownership or remove the
  last owner.
- `operator`: manage explicitly granted assistants/groups and their
  configuration; cannot manage memberships, secret values, or tenant-wide
  policy.
- `auditor`: read scoped configuration, revision, operational, and audit
  metadata; cannot mutate resources or view secrets/content.
- `viewer`: read only the minimum explicitly granted non-sensitive metadata.

Roles are capabilities, not proof of Telegram group authority. A control-plane
mutation that changes Telegram group behavior must verify the operator's
control-plane grant and the target resource scope. Existing Telegram command
mutations continue to require fresh platform-derived group authorization.

`deployment_operator` is a separate SPEC-025 deployment capability, not a role
in this tenant-role list. It is granted and revoked explicitly, audited without
a tenant scope, and evaluated from current durable state on each deployment
request.

### Scope evaluation

For every protected request, the authorizer evaluates:

1. authenticated identity and session status;
2. tenant membership and role;
3. resource ownership and parent relationship;
4. action capability;
5. explicit assistant, connection, or group grant where required;
6. resource status, such as disabled or pending deletion;
7. step-up or confirmation requirements for high-impact actions.

A missing, stale, contradictory, or unresolvable relationship fails closed.
Cross-tenant identifiers, guessed IDs, and client-supplied role claims never
expand authorization.

### High-impact actions

The following require tenant-owner capability plus recent authentication or
explicit confirmation:

- changing tenant ownership or removing an owner;
- adding, escalating, or disabling an operator membership;
- replacing a platform connection or secret reference;
- deleting or disabling an assistant, connection, or group binding;
- restoring an older configuration revision;
- exporting audit metadata.

The implementation must define a bounded step-up lifetime and record only a
content-free reason code.

## Authentication model

The control plane uses an approved external OIDC/OAuth2-compatible identity
boundary. Provider selection is deployment-owned and must not alter the
application authorization contract.

- The server validates issuer, audience, signature, expiry, nonce/state, and
  redirect/callback conditions according to the selected provider.
- Operator identity is keyed by `(issuer, subject)`, not email address or
  Telegram user ID.
- Sessions use secure, HttpOnly, SameSite cookies or short-lived bearer tokens
  according to the approved client type. CSRF protection is mandatory for
  cookie-authenticated mutations.
- Logout revokes the session or refresh boundary. Disabled membership and
  revoked identity are checked again on every protected request.
- The control plane never accepts a client-supplied role, tenant, or group
  scope as authoritative.
- MFA or equivalent strong authentication is required for tenant-owner and
  high-impact actions when supported by the selected identity boundary.
- Authentication failures disclose no tenant or resource existence and emit
  content-free audit/telemetry outcomes.

No local password database, password reset flow, or implicit Telegram-login
trust is introduced by this SPEC.

## Revision model

Mutable control-plane resources use immutable revisions and an explicit current
pointer.

- Every successful mutation creates a new revision or membership event.
- Revisions include a monotonically increasing resource version and parent
  version.
- Reads may request current state or a specific authorized historical revision.
- Mutations require `If-Match`/expected-version semantics or an equivalent
  explicit compare-and-swap token.
- A stale write returns a safe conflict response with current version metadata,
  never silently overwriting another operator's change.
- Restore creates a new revision whose parent is the current revision; it does
  not delete history.
- Historical revisions remain subject to tenant authorization and retention.
- Effective runtime behavior is associated with the committed revision ID so
  operators can explain which configuration was used without storing content.

## Concurrency model

- PostgreSQL is the authority for membership, ownership, bindings, revisions,
  and audit events.
- Resource-version compare-and-swap prevents lost updates.
- Database transactions cover only local state and audit intent. No lock or
  transaction remains open during external I/O.
- External platform work is idempotent, bounded, and represented by durable
  operation state where needed. Repeated client requests use an idempotency key
  and return the original operation result.
- Per-resource mutations are serialized by version and uniqueness constraints;
  unrelated tenants and resources remain independently concurrent.
- Authorization is re-evaluated when an asynchronous operation executes.
  Revocation prevents queued work from applying after access is removed.
- Ambiguous Telegram results retain the existing `delivery_unknown` policy and
  are never converted into generic control-plane retries.
- Conflict, authorization, and dependency failures are distinguishable and
  content-safe.

## API surface

The API is versioned, JSON-based, and intended for a future web dashboard and
CLI. Exact transport/framework details are implementation decisions; these
resource and authorization contracts are product authority.

### Authentication and operator context

- `GET /control/v1/session` — return the authenticated operator's safe session
  and tenant memberships.
- `POST /control/v1/session/logout` — revoke the current session.
- `GET /control/v1/me` — return safe identity and effective capabilities.

Unauthenticated requests return a generic authentication failure or login
challenge without revealing resource existence.

### Tenant and membership administration

- `GET /control/v1/tenants` — list authorized tenant summaries.
- `GET /control/v1/tenants/{tenant_id}` — read authorized tenant metadata.
- `GET /control/v1/tenants/{tenant_id}/members` — list scoped memberships.
- `POST /control/v1/tenants/{tenant_id}/members` — invite or provision an
  already-authenticated identity with a bounded role.
- `PATCH /control/v1/tenants/{tenant_id}/members/{member_id}` — change role,
  scope, or status subject to ownership safeguards.
- `DELETE /control/v1/tenants/{tenant_id}/members/{member_id}` — revoke access
  without deleting product data.

Membership responses contain no identity-provider tokens or secrets.

### Assistants and platform connections

- `GET/POST /control/v1/tenants/{tenant_id}/assistants`
- `GET/PATCH/DELETE /control/v1/tenants/{tenant_id}/assistants/{assistant_id}`
- `GET/POST /control/v1/tenants/{tenant_id}/connections`
- `GET/PATCH/DELETE /control/v1/tenants/{tenant_id}/connections/{connection_id}`
- `POST /control/v1/tenants/{tenant_id}/connections/{connection_id}/rotate`

Connection responses expose capability, status, secret-reference presence, and
last-validated metadata only. Secret values are write-only through the
approved external mechanism and are never returned.

### Groups and configuration

- `GET /control/v1/tenants/{tenant_id}/groups`
- `GET /control/v1/tenants/{tenant_id}/groups/{group_id}`
- `PATCH /control/v1/tenants/{tenant_id}/groups/{group_id}` — change binding
  and approved group settings with optimistic concurrency.
- `GET /control/v1/tenants/{tenant_id}/groups/{group_id}/revisions`
- `GET /control/v1/tenants/{tenant_id}/groups/{group_id}/revisions/{revision}`
- `POST /control/v1/tenants/{tenant_id}/groups/{group_id}/restore`

Group endpoints return policy metadata and effective revision identifiers, not
conversation content, raw memory, prompts, or private participant data.

### Operational and audit views

- `GET /control/v1/tenants/{tenant_id}/assistants/{assistant_id}/status`
- `GET /control/v1/tenants/{tenant_id}/connections/{connection_id}/status`
- `GET /control/v1/tenants/{tenant_id}/audit-events`

Operational and audit filters are bounded, tenant-scoped, and content-safe.
Pagination cursors must not disclose resources outside the authorized scope.

### Error contract

Protected endpoints use stable categories such as `authentication_required`,
`forbidden`, `not_found_or_forbidden`, `conflict`, `validation_error`,
`dependency_unavailable`, and `operation_pending`. Error bodies contain a
request ID and safe reason code, never credentials or private product content.

## CLI compatibility

- Existing Telegram commands remain backward compatible, including fresh
  current authorization for protected group changes and deterministic response
  behavior.
- No existing CLI or operator script may bypass the control-plane API by
  writing directly to PostgreSQL.
- A future operator CLI, if introduced, uses the same versioned API, identity
  boundary, role checks, revisions, idempotency keys, and error categories as
  the dashboard.
- Non-interactive automation uses short-lived scoped credentials or an
  approved workload identity, never copied human refresh tokens.
- CLI output is safe by default: secrets, message content, prompts, vectors,
  provider bodies, and unrelated tenant resources are never printed.
- Command names and existing Telegram command semantics are not renamed or
  repurposed by SPEC-021.

## Migrations

Implementation is expected to require additive durable state for operator
identities, tenant memberships, resource ownership/scopes, revisions, audit
events, and idempotent control-plane operations. SPEC-021 creates no migration.

The later implementation must:

- use expand/validate/contract sequencing;
- preserve all existing SPEC-001 through SPEC-020 tables and behavior;
- introduce nullable/additive structures before enforcing new invariants;
- backfill only synthetic or explicitly classified metadata, never copied
  production content without an approved privacy process;
- separate schema ownership from ordinary application access where supported;
- provide rollback by disabling control-plane routes or reverting compatible
  application configuration, not by routine destructive database downgrade;
- validate upgrade, downgrade/forward-fix policy, partial migration recovery,
  and concurrent old/new application behavior before production release.

No control-plane request may depend on an uncommitted migration or silently
create schema state at application startup.

## Security

- Authenticate before resource lookup and fail closed on every authorization
  uncertainty.
- Enforce tenant IDs and parent relationships server-side; prevent IDOR and
  cross-tenant enumeration with generic not-found/forbidden responses.
- Use secure session/token handling, CSRF protection where applicable, bounded
  expiration, revocation, step-up authentication, and replay-resistant state.
- Validate redirect URIs, issuer/audience, scopes, resource IDs, versions,
  idempotency keys, and all operator input.
- Apply least privilege to database roles, background operations, secret
  references, and audit readers.
- Never log access tokens, cookies, authorization headers, secret references
  that reveal values, or sensitive request bodies.
- Rate-limit authentication, membership mutation, secret-reference mutation,
  audit export, and high-impact actions.
- Require confirmation and audit events for ownership transfer, access
  escalation, deletion/disablement, restore, and connection rotation.
- Keep platform actions inside adapters and preserve existing Telegram
  ambiguity and safety policies.
- Do not treat an email address, Telegram user ID, client role, or UI control as
  sufficient authentication or authorization evidence.

## Privacy

- Control-plane data is tenant-scoped and access-minimized.
- Audit records store actor/resource/action/outcome metadata, not messages,
  prompts, memories, vectors, provider bodies, or credentials.
- Conversation content and private participant data are not included in group
  administration responses by default.
- Identity metadata is limited to what is needed for display, authorization,
  support, and audit; upstream tokens are never persisted as product data.
- Membership revocation removes access promptly without resurrecting deleted
  content or derived memory.
- Revision and audit retention follows an explicit deployment policy and
  supports deletion/anonymization where legally and operationally required.
- Staging and test control-plane data use synthetic identities and resources;
  production content is never copied into them.
- Telemetry, errors, health responses, and CLI output remain content-safe.

## Validation plan

The implementation phase must add focused and integration proof without
weakening the existing matrix.

### Authentication and authorization

- valid, expired, revoked, malformed, wrong-issuer, and wrong-audience tokens;
- disabled identities and revoked memberships;
- every role/action/resource-scope combination;
- cross-tenant ID guessing and pagination isolation;
- ownership transfer, last-owner protection, escalation, and step-up flows;
- no authorization based solely on Telegram identity or client claims.

### Revisions and concurrency

- create/update/restore produces immutable revisions;
- stale `If-Match` or compare-and-swap requests return safe conflicts;
- concurrent authorized edits do not lose updates;
- duplicate idempotency keys do not create duplicate durable effects;
- revocation before queued execution prevents the operation.

### API and CLI

- request/response schemas, stable errors, request IDs, pagination, and
  redaction;
- secret values never appear in responses, logs, metrics, audit, or CLI output;
- existing Telegram command integration and authorization regressions;
- future CLI contract tests use the same API and authorization path.

### Persistence and recovery

- migration upgrade and compatibility validation;
- partial migration and forward-fix recovery;
- restore/revision rollback without deleting history;
- audit event durability and content-safe failure behavior;
- API and worker restart during local control-plane mutation or external I/O.

### Existing guarantees

Run the complete SPEC-001 through SPEC-020 validator matrix, including
privacy, safety, retention, semantic memory, summaries, observability,
recovery, rate limiting, ambient participation, idempotency, concurrency,
Docker, migration, Compose, and deployment checks.

## Acceptance criteria

- An authenticated operator can access only authorized tenants and resources.
- Tenant owner/admin/operator/auditor/viewer capabilities are enforced
  server-side and documented in the API contract.
- Cross-tenant reads, writes, pagination, audit access, and operation results
  fail closed without resource enumeration.
- No control-plane operator action silently grants Telegram group-admin power;
  existing Telegram fresh-authorization rules remain intact.
- Assistants, connections, groups, memberships, and configuration revisions
  can be inspected and managed through the versioned API.
- High-impact actions require the documented role, confirmation, and recent
  authentication boundary.
- Every successful sensitive mutation creates an immutable revision/event and
  a content-safe audit record.
- Stale concurrent writes are rejected without lost updates.
- Duplicate requests and retries do not create duplicate durable effects.
- Secrets and identity-provider credentials are never returned or logged.
- A future web client and CLI can use the same API without direct database
  access or authorization duplication.
- Migration, rollback/forward-fix, revocation, recovery, and cleanup behavior
  are executable or observable in the implementation phase.
- Existing SPEC-001 through SPEC-020 behavior and validator matrix remain
  green.
- Product, architecture, privacy, and security documentation remain accurate;
  no runtime feature outside SPEC-021 is introduced.

## Implementation phases

1. **Authority and identity boundary** — select the hosting/deployment identity
   integration, define issuer/audience/session policy, create ADRs required by
   the chosen provider, and finalize resource ownership terminology.
2. **Durable control-plane foundation** — add additive schema and repositories
   for identities, memberships, tenants, resource bindings, revisions, audit,
   and idempotent operations; validate migration compatibility.
3. **Authentication and authorization middleware** — implement provider
   validation, session lifecycle, CSRF/step-up behavior, deny-by-default
   authorization, tenant isolation, and content-safe telemetry.
4. **Versioned management API** — implement operator context, membership,
   assistant, connection, group, revision, status, and audit endpoints with
   stable errors and optimistic concurrency.
5. **Dashboard/CLI integration boundary** — provide client contracts, safe
   pagination, redaction, and API-only CLI compatibility without direct DB
   access or Telegram command changes.
6. **Recovery and security rehearsal** — validate revocation, stale writes,
   duplicate requests, partial migrations, restore/forward-fix, audit privacy,
   dependency failure, and restart during external I/O.
7. **Controlled acceptance** — run the complete legacy matrix, review security
   and privacy evidence, approve staging resources, and obtain operator
   acceptance before production exposure.

## Risks

| Risk | Required mitigation |
|---|---|
| Cross-tenant data leak | Mandatory tenant-scoped queries, deny-by-default policy, isolation tests, generic not-found/forbidden errors. |
| Privilege escalation | Server-side capability matrix, last-owner safeguards, step-up authentication, audit review. |
| Identity-provider misconfiguration | Issuer/audience validation, provider contract tests, safe startup refusal, staged rollout. |
| Stale administrative overwrite | Immutable revisions, compare-and-swap, explicit conflict response, no blind retry. |
| Duplicate external effect | Idempotency keys, durable operation state, authorization recheck, adapter ambiguity policy. |
| Secret exposure | External secret references, write-only handling, redaction tests, restricted audit/CLI output. |
| Control plane bypass | API-only clients, no direct DB CLI, shared authorization service, CI contract checks. |
| Privacy expansion | Metadata-only responses, content-free audit, synthetic staging data, retention policy. |
| Migration incompatibility | Additive expand/validate/contract process, old/new compatibility, forward-fix recovery. |
| Existing Telegram regression | Preserve command routes and fresh platform authorization; run the full legacy matrix. |

## Dependencies

- SPEC-001 through SPEC-020 accepted contracts and executable validators.
- SPEC-009 personality and group configuration revisions.
- SPEC-010 Telegram administration commands and fresh authorization.
- SPEC-011 privacy, retention, and forget semantics.
- SPEC-012 safety and distributed rate limiting.
- SPEC-015/016 observability and operational recovery boundaries.
- SPEC-017 ambient participation controls.
- SPEC-018 summaries and bounded context behavior.
- SPEC-019 semantic-memory scope, revalidation, and rebuildability.
- SPEC-020 deployment, secrets, lifecycle, readiness, migration, and recovery
  boundaries.
- Product Owner approval of identity-provider boundary, tenant model, role
  matrix, session/MFA policy, audit retention, and control-plane exposure.
- Deployment-owner selection of the external identity provider, secret
  manager, hosting target, TLS boundary, and operational ownership.

## Rollback and recovery

Control-plane rollout uses feature-gated, additive deployment. If the control
plane is unsafe or unavailable, disable its routes or client exposure while
leaving the existing Telegram runtime and command path operational. Revert to
the last compatible application image/configuration only when schema
compatibility is proven. Correct failed schema changes with forward-compatible
migrations; do not routinely downgrade production databases.

Restore PostgreSQL according to SPEC-020, reconstruct Redis coordination, and
rebuild Qdrant from PostgreSQL as needed. Revoke sessions and memberships after
an authorization incident, preserve content-free audit evidence, and never
replay ambiguous Telegram delivery as a generic control-plane recovery step.

## Observable completion evidence

Implementation completion requires the versioned API contract, migration and
authorization tests, redaction and tenant-isolation evidence, revision and
concurrency proof, recovery rehearsal, full legacy validator results, and an
updated implementation handoff. Production acceptance additionally requires
the selected identity provider, approved staging/production resources, TLS,
monitoring, audit ownership, backup/rollback destinations, and operator sign-off.
