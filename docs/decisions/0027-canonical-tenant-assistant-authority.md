# 0027 Canonical Tenant and Assistant Authority

Date: 2026-09-11

## Status

Accepted under the Product Owner-authorized SPEC-030 implementation.

## Context

The existing control plane already has durable tenants, external operator
identities, tenant memberships, and a separate deployment authority. Core
Assistants and PlatformConnections predate that control plane. Their tenant
attribution is stored in separate control binding tables, while memory and
provider records repeat resource IDs without complete cross-table constraints.
Bootstrap can also create an unbound Assistant. These paths can disagree and
make a request tenant or optional mirror row look authoritative.

## Decision

Reuse `control_tenants` as the sole durable tenant and the existing membership
and deployment-authority systems as the sole role authorities.

Store immutable `tenant_id` on every Assistant. Store constrained `tenant_id`
on every PlatformConnection and enforce `(assistant_id, tenant_id)` against its
Assistant. Conversations derive Assistant and tenant through their immutable
connection rather than copying authority columns. Exact-scope memory keeps its
operational Assistant/connection/conversation columns but composite foreign
keys make disagreement impossible. Provider resource scopes likewise use
composite tenant/resource foreign keys.

Database triggers reject Assistant tenant reassignment and any connection
tenant/Assistant reassignment, including a same-tenant rebind that ordinary
foreign keys could otherwise permit. This keeps existing conversations,
schedules, memory, usage, privacy, and audit history attached to their original
Assistant authority.

Existing assistant/connection control bindings remain temporarily as
compatibility indexes. Composite foreign keys bind them to canonical core
ownership, so they can no longer assign a different tenant and are not used as
the root of new authorization or runtime attribution.

Tenant, Assistant, and connection lifecycle is revisioned. New Assistants and
connections start disabled; retired resources are terminal. Authority fields
cannot be patched or rebound. Every provider and Telegram external-I/O path
revalidates the current tenant, Assistant, and connection state after work is
claimed and before I/O.

Legacy unbound Assistants are assigned only to one reserved legacy tenant that
represents the former deployment-wide administrative boundary. Existing tenant
bindings are preserved; contradictory relationships block migration instead of
being guessed or reparented.

## Consequences

- Multiple Assistants per tenant and multiple tenants are explicit in the core
  graph; a connection/update resolves deterministically to one owner chain.
- Cross-tenant resource combinations are rejected by the database and do not
  depend on opaque UUID secrecy.
- Conversation-scoped participants, memory, and schedules do not become a
  federated user identity or cross-assistant data surface.
- Provider scopes remain deployment, Assistant, and PlatformConnection only;
  no tenant budget or billing model is added.
- Tenant roles and `deployment_operator` remain separate. Deployment authority
  alone never grants tenant content access.
- Migration `0021_multi_assistant_tenancy` is guarded when downgrade would
  discard canonical ownership or revision/lifecycle state.

## Alternatives considered

1. Add a new Tenant/Organization/Workspace graph: rejected because
   `control_tenants` and memberships already own that responsibility.
2. Keep control binding tables as unconstrained authority: rejected because
   missing/mismatched rows can bypass or misattribute resource policy.
3. Copy tenant and Assistant IDs onto every descendant: rejected because
   conversations and schedules already have safe canonical FK paths; only
   operational duplicates with enforceable consistency remain.
4. Permit Assistant or connection reassignment: rejected because conversation,
   memory, schedule, provider usage, privacy, and audit history cannot be safely
   retargeted by a casual metadata update.
