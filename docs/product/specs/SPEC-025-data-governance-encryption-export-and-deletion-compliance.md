# SPEC-025 Data Governance, Encryption, Export, and Deletion Compliance

## Status

APPROVED PRODUCT SPEC AND IMPLEMENTATION AUTHORITY. The Product Owner approved
the product contract and, on 2026-08-13, explicitly authorized its SPEC-025
runtime implementation, migration `0016_data_governance`, tests, validators,
ADR, runbooks, deployment wiring, and audit remediation. The repository
candidate remains under final validation; production rollout and the external
operating-owner decisions declared below are not self-approved by this status.
On 2026-09-02 the Product Owner additionally authorized the bounded
`deployment_operator` authority required by FR-04. It is independent of all
tenant roles and extends the existing SPEC-021 authenticated identity boundary
without granting tenant access.

SPEC-024 is accepted and its implementation is an approved candidate whose
threshold objectives remain operating-owner approvals. SPEC-023 is implemented
as an approved candidate pending ratification of its proposed objectives and
notification channels. SPEC-020 is an approved candidate pending external
deployment acceptance. SPEC-022 live Telegram acceptance remains an externally
gated operational step. SPEC-014 remains deferred behind its Zalo prerequisite
and no Zalo runtime is authorized. SPEC-025 does not begin a later
specification and does not change the safety, privacy, memory, rate-limit,
administration, or observability contracts it builds on.

## Product goals

Lumi stores data across several surfaces: conversation and message records,
explicit memory, privacy and protection state, configuration revisions, safety
decision records, audit events, derived summaries, a derived semantic index,
and operational telemetry. Today the product protects that data well but does
not govern it as a single, user-facing contract: a member cannot obtain a
portable copy of their own data, erasure is implemented across separate
features rather than declared as one guarantee, encryption is delegated to
operator infrastructure without a declared ownership boundary, and no
compliance posture is written down.

SPEC-025 makes data governance a product surface. It defines, in one
authoritative contract, what Lumi stores, who may export it, how it is deleted,
how long it is retained, who owns encryption, and which compliance regimes the
product claims technical alignment with. It does not invent new processing: it
formalizes, completes, and documents the lifecycle of the data the product
already handles, and it makes export and erasure first-class, observable
product behaviors.

The contract must hold unchanged if a Zalo adapter is later enabled under the
same platform-independent core.

## Problem statement

1. Data inventory is implicit. No single product document lists every stored
   category, its purpose, its retention basis, and whether a user controls it.
   Export, deletion, and retention decisions therefore cannot be complete or
   auditable.
2. There is no product-level export. A member or group administrator has no
   way to receive a portable, bounded copy of the data Lumi holds for them.
3. Erasure is feature-scattered. Privacy deletion, memory deletion, retention,
   and derived-index behavior exist (SPEC-011, SPEC-018, SPEC-019) but are not
   declared as one erasure guarantee with completion status and audit.
4. Encryption ownership is undeclared. The product requires HTTPS and never
   persists secrets (SPEC-020), but there is no single statement of what Lumi
   guarantees, what the operating owner must provide, and what is
   intentionally not provided.
5. There is no compliance posture. Whether and how the product aligns with
   regulations such as GDPR, CCPA/CPRA, or LGPD is nowhere declared, which
   makes operator obligations and product boundaries ambiguous.
6. Backup behavior is operational only. The relationship between backups and
   deletion, retention, and erasure is documented as a runbook, not as a
   product contract a user can rely on.

## Scope

In scope:

- A maintained inventory of every data category the product stores, with
  purpose, storage surface, retention basis, and user control.
- Data export for three scopes: the data subject, the group administrator
  (group configuration and stored data), and the operating owner (content-free
  deployment snapshot).
- Erasure on request for a data subject, including completion status, derived
  surfaces, and audit.
- Group and conversation deletion and reset, including all derived surfaces.
- Retention schedules per data category and their automated enforcement.
- The declared relationship between backups, deletion, retention, and erasure.
- A single, documented encryption ownership boundary: in transit, at rest,
  backups, and key management.
- A single, documented compliance posture with explicit assumptions.
- Governance audit events for export and deletion in the existing content-safe
  audit surface.
- User-facing transparency: a plain-language data summary available to users.

Out of scope:

- Capabilities beyond the authorized SPEC-025 runtime, migration, validation,
  ADR, runbook, and deployment work required by this contract.
- Certification, audits, or attestations (SOC 2, ISO 27001, GDPR certification
  or similar). SPEC-025 declares technical alignment claims only; certification
  is an operating-owner and external-audit concern outside the product.
- Legal obligations of the controller/processor relationship: data processing
  agreements, legal basis decisions, sub-processor contracts, cross-border
  transfer mechanisms, breach notification, and supervisory-authority
  interactions. These are operator obligations, not product behavior.
- Consent-management systems. Existing per-feature opt-in and opt-out controls
  remain; a general consent register is future work (see Roadmap).
- End-to-end encryption, client-side encryption, or encryption of
  user-to-user message content within the platform. Messaging content is
  processed by the platform operator under the declared ownership boundary.
- Any change to existing safety, privacy, memory, rate-limit, or authorization
  contracts (SPEC-011, SPEC-012, SPEC-021, SPEC-024). SPEC-025 adds governance
  surfaces without weakening them.
- Import of exported data into another service or instance. Portability
  import/transmission is future work.
- Public reporting features, billing data processing, or monetization data.
- New platform adapters; Zalo runtime remains deferred behind SPEC-014.
- Moderation of general user-to-user content (SPEC-024 boundary).

## Glossary

- **Data subject:** an identifiable natural person whose data Lumi stores — a
  group member or a private-conversation user.
- **Group administrator:** a Telegram group administrator acting within that
  group's scope (SPEC-010 authorization model).
- **Operating owner:** the technical operator responsible for the deployment
  (SPEC-020/SPEC-021 authorization model).
- **Controller / processor:** legal roles defined by data-protection law. The
  operating owner is the data controller for the deployment; Lumi is the data
  processing software. SPEC-025 declares this boundary, not a contract.
- **Erasure:** deletion or irreversible anonymization of a subject's data such
  that it cannot be restored into active product use through any product path.
- **Derived surfaces:** data produced from source data rather than stored
  directly by the user or platform — conversation summaries and the derived
  semantic index.
- **Content-safe:** carries counts, opaque references, and closed classes only;
  never message text, prompts, memories, vectors, tokens, credentials,
  usernames, or raw platform identifiers (SPEC-015, SPEC-023, SPEC-024).

## Functional requirements

Each requirement is labeled `[Baseline]` (implemented by an accepted earlier
specification) or `[New]` (introduced and implementation-authorized by
SPEC-025). The current repository implementation is a release candidate under
final validation; the labels do not defer the authorized runtime work.

### FR-01: Data inventory and classification `[New]`

The product shall maintain an explicit, versioned register of every data
category it stores. For each category the register records: purpose; the
storage surface (primary database, derived index, coordination layer,
operational telemetry, or audit); the retention basis; and whether the data is
user-controlled (subject, group administrator, or operating owner). The
register is the authoritative input for export, deletion, and retention
behavior. It must reflect the actual data the product stores and be reviewed
whenever data storage changes.

### FR-02: Subject data export `[New]`

A data subject shall be able to request a portable, bounded copy of the data
Lumi holds about them within a conversation scope. The export shall be a
versioned, machine-readable package (JSON) with a manifest stating its scope,
categories, and timestamp. It shall include the subject's own stored data —
profile and preference state, opt-out and protection state, explicit memories
stored by the subject within the conversation scope, and the subject's own
message content — and shall exclude other subjects' content, credentials,
secrets, and raw platform identifiers of other people. Export shall be
requested asynchronously, expire after a bounded period, be delivered through
a single-use authorized channel, and be rate limited. Only the subject, with
verified identity, may request a subject export.

### FR-03: Group-administrator export `[New]`

A group administrator shall be able to request a bounded export of the
group-scoped data Lumi stores for that group: group configuration, personality
and safety settings, revision history, and group-level stored data. Message
content of individual members is not included in a group export; member content
is available only through the per-subject export in FR-02. Group exports
require current group authorization and are asynchronous, bounded, expiring,
single-use, and audited.

### FR-04: Operating-owner deployment export `[New]`

The operating owner shall be able to request a content-free deployment-scoped
snapshot for governance purposes: data categories and volumes, retention state,
retention and erasure configuration, and governance audit records. It shall
contain counts and configuration only — never message content, memories,
prompts, credentials, or raw platform identifiers. It requires operating-owner
authorization and is audited. Repository enforcement represents that authority
as a durable, explicitly granted `deployment_operator` capability on an existing
SPEC-021 control-plane identity. Tenant ownership or administration never
implies this capability, and the capability never implies tenant membership.
Grant, revoke, denial, and authorized export decisions are content-safe audited
events. Revocation is authoritative on the next request.

### FR-05: Erasure on request `[New]`

A data subject shall be able to request erasure of their data. The product
shall erase or irreversibly anonymize the subject's data across all primary
product surfaces, expire or redact derived summaries that reference the
subject, and ensure the derived semantic index cannot surface the erased data
(consistent with the existing rebuildable-index behavior in SPEC-019). Technical
tombstones without content may remain. Erasure shall not be reversible through
any product path. `/forget_me` and `/forget_me confirm` remain the subject-facing
entry points and continue to work as today.

### FR-06: Erasure completion and status `[New]`

Every erasure request shall produce a trackable, content-free status:
requested, in progress, complete, or partial with an explicit reason. The
status shall be accessible to the subject and recorded in the audit surface.
A partial outcome must be explicit and repeatable; the product may not silently
leave data un-erased.

### FR-07: Group and conversation deletion and reset `[Baseline, extended]`

The existing group memory reset and privacy deletion behavior remains. SPEC-025
extends the contract by declaring the full surface a group reset or a
conversation deletion covers: memory items, stored configuration where
applicable, derived summaries, and derived-index points for that scope. The
declared coverage is the same completeness guarantee as FR-05 applied to a
group scope.

### FR-08: Retention schedules `[Baseline, extended]`

The product shall enforce and document a retention schedule per data category.
Existing baselines remain authoritative: raw message content is bounded (up to
30 days by default, enforced automatically); explicit memory persists until
deleted, expired, or erased; summaries expire at the earliest source-message
deadline; safety decision records and audit events are bounded; telemetry is
aggregated and content-free. SPEC-025 adds a single written schedule covering
every category in the inventory, states which schedules are enforced
automatically and which are operator-configurable, and treats schedule changes
as configuration — never as ad-hoc deletion.

### FR-09: Backup and restore semantics `[Baseline, extended]`

The product shall declare how backups relate to deletion, retention, and
erasure. Baseline: backups are operator-managed copies for recovery, with a
documented and rehearsed backup/restore procedure. SPEC-025 adds the contract
that: (a) erasure applies to live product state and tombstones contained in a
backup remain authoritative after restore; (b) a backup predating a later
erasure must not be promoted until the operating owner reapplies post-backup
erasures from an external operating record, because this repository does not
provide an out-of-backup erasure ledger; (c) a subject erasure is bounded by
the most recent backup taken before the erasure, which the operating owner must
purge under the declared backup-retention and purge policy; and (d) this
boundary is disclosed to users in plain language (FR-13).

### FR-10: Encryption ownership `[New]`

The product shall declare a single encryption ownership model covering:
in-transit, at-rest, backups, and key management. The declaration must state,
for each surface, who provides the control (the product or the operating
owner), what the product guarantees, and what the product intentionally does
not provide. Baseline commitments (SPEC-020) remain: secrets are injected at
the process boundary, never persisted in the database or logs, never logged,
and rotated through the documented procedure. SPEC-025 adds application-level
field encryption as an explicitly non-provided capability (future work), and
requires the backup procedure to mandate encrypted backups.

### FR-11: Compliance posture `[New]`

The product shall declare its compliance assumptions in one authoritative
document: the regimes it claims technical alignment with (for example GDPR,
CCPA/CPRA, and LGPD as alignment claims, not certification), the obligations
that fall on the operating owner (legal basis, data processing agreements,
sub-processors, breach notification, cross-border transfers, children's-data
policy), and what the product does not provide (no certification, no
end-to-end encryption, no legal advice). No compliance claim may be asserted
in product surfaces or documentation beyond this declared posture.

### FR-12: Governance audit `[New]`

Every export and erasure request, completion, and failure shall be recorded in
the existing content-safe audit surface. Audit records shall carry opaque
request and scope references, timestamps, and closed outcomes — never content,
credentials, or secrets — and shall be subject to a bounded retention
schedule. Export and erasure are added to the same audit discipline as existing
administration and safety events.

### FR-13: User-facing transparency `[New]`

The product shall expose a plain-language data summary to users, available in
the product (for example through an informational command or documented help)
and in public product documentation, stating: what data Lumi stores, how to
request an export, how to request deletion, how long data is retained, and who
owns encryption. The summary shall be written for a non-technical audience and
must not claim more than FR-10 and FR-11 declare.

## Non-functional requirements

### NFR-01: Content-safe governance artifacts

Every export manifest, export package metadata, erasure status, retention
schedule, governance audit record, and compliance statement is content-safe
under the SPEC-015/023/024 discipline. Subject exports (FR-02) are the sole
exception: they contain the subject's own data by definition.

### NFR-02: Asynchronous and non-blocking

Export and erasure jobs never run inside the webhook acknowledgement path,
never block provider or Telegram I/O, and never degrade webhook
acknowledgement latency. They run as bounded background work.

### NFR-03: Idempotency and retry

Export and erasure operations are idempotent and retryable: a repeated request
for the same scope does not duplicate an export or re-erase; failures retry
according to the existing recovery model without unbounded retry or loops
(SPEC-016).

### NFR-04: Authorization scope

Subject exports require verified subject identity; group exports require fresh
current group authorization (SPEC-010); deployment exports require
an active, explicitly granted `deployment_operator` authority on an
authenticated SPEC-021 identity. Deny-by-default applies to every governance
surface; tenant membership is neither group authority nor deployment authority,
and deployment authority does not confer tenant membership.

### NFR-05: Fail-closed completion

If erasure cannot complete, the product reports a partial outcome with an
explicit reason (FR-06); it never silently skips. Export delivery fails safe
and can be retried within its validity window.

### NFR-06: Testability

All governance behavior is testable without a real platform, an LLM, or a
network connection, using the repository's existing testability discipline
(SPEC NFR-006). Product acceptance criteria in this document are observable
without requiring external services.

### NFR-07: Scalability and locking

Export and erasure operate in bounded batches, use the existing lease and
idempotency model, and hold no database lock across external I/O (SPEC-016).

### NFR-08: Availability

Governance features are optional, separately enabled capabilities. They never
change readiness semantics for the core product and never affect `/ready`
dependencies beyond their own optional surfaces.

## Privacy requirements

- **Data minimization:** the product stores only the data the accepted
  specifications define; the inventory (FR-01) documents purpose and limits for
  every category.
- **Purpose limitation:** each category's purpose and retention basis are
  documented; data is not used beyond its declared purpose.
- **Scope isolation:** memory, context, and privacy isolation across
  conversations remain authoritative (SPEC-011); governance surfaces operate
  within the same scope rules.
- **Erasure precedence:** a subject's erasure request takes precedence over
  retention schedules for that subject's data.
- **No profiling:** export, erasure, and governance surfaces never build
  reputation scores, profiles, or sanctions against members (SPEC-024
  boundary). Governance is about data lifecycle, not member behavior.
- **Consent:** existing per-feature opt-in and opt-out controls (for example
  ambient participation and teasing/mention opt-outs) remain the product's
  control model. SPEC-025 introduces no new consent-management system; a
  general consent register is future work.
- **Children's data:** the product has no age-gating feature; children's-data
  obligations are declared as an operating-owner responsibility in the
  compliance posture (FR-11).
- **Content safety preserved:** governance never reintroduces rejected
  content, private-memory disclosure, or raw platform identifiers into any
  surface.

## Data governance requirements

- The data inventory (FR-01) is authoritative and versioned; any change to what
  the product stores updates the inventory in the same change.
- The product recognizes three governing scopes — subject, group, deployment —
  with matching authorization (NFR-04) and matching export/erasure surfaces.
- Retention is automated where the baseline already automates it and
  documented for every category (FR-08).
- Governance behavior is identical regardless of platform adapter; the contract
  holds if a Zalo adapter is later enabled.
- When multi-tenant operation is later introduced, every governance surface
  must be expressible per tenant; SPEC-025 defines the per-deployment contract
  now and records per-tenant expressibility as future work.

## Export requirements

- Formats: versioned JSON packages with a manifest (scope, categories,
  timestamp, schema version).
- Scopes and owners: subject (FR-02, verified identity), group administrator
  (FR-03, current group authorization), operating owner (FR-04, content-free).
- Delivery: asynchronous, single-use, expiring, rate-limited, audited.
- Boundaries: no other subjects' content; no credentials, tokens, secrets, or
  raw platform identifiers of other people; subject export may include the
  subject's own content only.
- Import: explicitly out of scope; cross-service portability import is future
  work.

## Deletion requirements

- Scopes: subject (FR-05), group/conversation (FR-07), and the declared
  boundary for the deployment copy in backups (FR-09).
- Surfaces: primary database, derived summaries, derived semantic index, and
  coordination layers. Coordination layers are ephemeral and carry no
  persistent user content.
- Semantics: erasure or irreversible anonymization; technical tombstones
  without content may remain; erased data is unrecoverable through any product
  path, including derived-index rebuild.
- Execution: asynchronous, batched, idempotent, retryable, and reported
  complete or partial-with-reason (FR-06).
- Audit: every deletion event, outcome, and failure is recorded content-free
  (FR-12).

## Backup implications

- Backups are operational copies for recovery and remain operator-managed.
- The product declares that erasure applies to live state; backup copies taken
  before an erasure may contain the erased data and must be purged by the
  operating owner under the declared backup-retention and purge policy.
- Restore must not resurrect erased data into active context. Tombstones in the
  restored backup remain authoritative; if the backup predates an erasure,
  workers and derived-index rebuild remain stopped until the operating owner
  reapplies and verifies post-backup erasures from an external record (FR-09).
- The backup procedure must mandate encryption of backups and encrypted
  transport for any off-site copy (FR-10).
- The existing rehearsed backup/restore procedure remains baseline and is not
  weakened.

## Encryption ownership

The product declares, in one authoritative model:

| Surface | Owner | Product guarantee | Not provided |
| --- | --- | --- | --- |
| In transit | Operating owner provides TLS/HTTPS; product requires it | Webhook requires HTTPS; secrets never sent in cleartext by the product | — |
| At rest — database and volumes | Operating owner (storage/volume encryption) | Product persists no plaintext secrets at rest | Application-level field encryption |
| At rest — secrets | Product | Secrets injected at the process boundary, never persisted in the database, logs, or audit, never logged | — |
| Derived index (Qdrant) | Product | Content-free opaque points; rebuildable | Memory text never stored in the index |
| Backups | Operating owner | Backup procedure mandates encryption | — |
| Key management | Operating owner | Rotation procedure exists (SPEC-020); keys never logged | — |
| Logs, metrics, audit | Product | Content-safe by construction | — |

Application-level field encryption is explicitly future work, not a current
guarantee.

## Compliance assumptions

- The product claims **technical alignment**, not certification, with data
  protection frameworks such as GDPR, CCPA/CPRA, and LGPD where the behaviors
  in this specification are implemented.
- **Controller/processor:** the operating owner is the data controller for the
  deployment; Lumi is the data processing software. This is a product-stated
  assumption, not a contractual commitment.
- **Operator obligations:** legal basis, data processing agreements,
  sub-processor management, cross-border transfer mechanisms, breach
  notification, supervisory-authority interaction, and children's-data policy
  are operating-owner obligations, not product behavior.
- **Not provided:** no SOC 2 / ISO 27001 / GDPR certification, no end-to-end
  encryption, no legal advice, no consent-management system.
- **Boundary of erasure:** erasure covers live product state; backup copies
  predating an erasure are governed by the declared purge policy (FR-09).
- **Review cadence:** the compliance posture and data inventory are reviewed
  whenever data storage changes and at least annually by the Product Owner and
  operating owner.

## Acceptance criteria

Each criterion is product-observable; none presumes implementation details.

- **AC-01 (FR-01):** A reader of the public product documentation can list
  every data category Lumi stores, its purpose, its storage surface, its
  retention basis, and who controls it.
- **AC-02 (FR-02):** A data subject with verified identity can request an
  export of their own data and receive a bounded, versioned JSON package with a
  manifest containing their own data and no other subject's content, no
  credentials, and no secrets.
- **AC-03 (FR-03):** A group administrator with current group authorization can
  request and receive a group-scoped export containing group configuration and
  stored group data and no member message content.
- **AC-04 (FR-04):** The operating owner can request a content-free
  deployment-scoped governance snapshot containing counts and configuration and
  no content. An explicit active `deployment_operator` can request it; ordinary
  tenant owners/admins and group admins cannot, and revocation takes effect on
  the next authorization decision.
- **AC-05 (FR-05):** A data subject can request erasure, and afterwards their
  data cannot be surfaced through memory, context, summaries, or the derived
  index through any product path.
- **AC-06 (FR-06):** Every erasure request shows one of the declared statuses;
  a partial outcome carries an explicit reason and can be retried.
- **AC-07 (FR-07):** A group memory reset or conversation deletion covers the
  declared full surface, and the documentation states exactly what is covered.
- **AC-08 (FR-08):** A single published retention schedule exists for every
  category in the inventory, distinguishing automatically enforced schedules
  from operator-configurable ones.
- **AC-09 (FR-09):** The public contract states the backup/erasure boundary,
  and a restore rehearsal cannot re-introduce an erased item into active
  context.
- **AC-10 (FR-10):** A single authoritative encryption-ownership document
  exists covering all surfaces in the matrix, and the backup procedure mandates
  encrypted backups.
- **AC-11 (FR-11):** A single compliance-posture document exists that states
  alignment claims, operator obligations, and non-provided capabilities, and no
  product surface overstates it.
- **AC-12 (FR-12):** Export and erasure requests, completions, and failures
  appear in the content-safe audit surface with opaque references and closed
  outcomes.
- **AC-13 (FR-13):** A plain-language data summary is available to users and
  public documentation, accurately describing storage, export, deletion,
  retention, and encryption ownership.

## Implemented vs future work

| Capability | Earlier baseline | Authorized SPEC-025 candidate |
| --- | --- | --- |
| Data inventory | Implicit across SPECs and documentation | Versioned, authoritative data register (FR-01) |
| Subject erasure | `/forget_me confirm` erases/anonymizes primary state (SPEC-011) | Full-surface erasure contract with completion status and derived-index coverage (FR-05, FR-06) |
| Retention | Raw-content retention ≤ 30 days; summaries expire; bounded safety/audit records (SPEC-011/018/023/024) | One published per-category schedule distinguishing enforced vs configurable (FR-08) |
| Derived index | Rebuildable, content-free, revalidated; forgotten data cannot reappear (SPEC-019) | Declared erasure guarantee across derived surfaces (FR-05) |
| Export | None | Subject, group, and deployment exports (FR-02/03/04) |
| Transparency | /help and documentation | Plain-language data summary (FR-13) |
| Encryption | Secrets never persisted/logged; HTTPS required; rotation procedure (SPEC-020) | Declared ownership matrix; encrypted-backup mandate; explicit non-provided capabilities (FR-10) |
| Compliance posture | None | Single declared posture with assumptions and operator obligations (FR-11) |
| Governance audit | Content-safe audit surface for administration and safety (SPEC-021/024) | Audit events for export and erasure (FR-12) |
| Backup/restore | Rehearsed backup/restore runbook (SPEC-020) | Declared backup/erasure/retention boundary (FR-09) |
| Consent management | Per-feature opt-in/opt-out only | General consent register (future work, not in this spec) |
| Portability import | None | Cross-service import (future work, not in this spec) |
| Field encryption | None | Application-level field encryption (future work, not in this spec) |

## Alignment with the approved roadmap

SPEC-025 aligns with the post-MVP product scope already approved in the product
contract: the user-controlled memory interface, long-term semantic memory, and
multi-tenant operation. The data inventory, export, and erasure surfaces defined
here are the foundation those roadmap items require, and are defined now so
that later roadmap work inherits one governance contract rather than several
inconsistent ones. Nothing beyond the product contract defined in this document
is authorized.

## Update rule

When data storage behavior changes, this specification's inventory, retention
schedule, and acceptance criteria are updated in the same change. When the
compliance posture or encryption ownership changes, the Product Owner and
operating owner approve the update explicitly.
