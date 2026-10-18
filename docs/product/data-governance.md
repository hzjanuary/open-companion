# Data Governance, Export, and Deletion

This is the public-facing data-governance reference for January (SPEC-025). It
states what January stores, how long, how to export, how to delete, and who owns
encryption. The authoritative documents for encryption ownership and the
compliance posture are separate: [encryption-ownership.md](encryption-ownership.md)
and [compliance-posture.md](compliance-posture.md).

## Plain-language data summary (FR-13)

January is a group assistant. To behave like one it stores:

- **Tenant and Assistant administration** — content-free durable tenant,
  Assistant, platform-connection, membership, lifecycle, and revision metadata.
  A deployment operator may provision a tenant but gains no tenant content
  authority; tenant administration never exposes messages, memory, schedules,
  transcripts, or participant identity.
- **Conversation and membership state** — what groups it belongs to, who is in
  them, and their configuration. This persists for the life of the
  conversation.
- **Messages and replies** — the message text it processes and the replies it
  sends. Raw content is automatically removed after at most 30 days.
- **Media-derived content (SPEC-028 candidate)** — captions, source-scoped file
  metadata and successful voice/audio transcripts. Transcripts are derived user
  content, not typed text or explicit memory. Downloaded image/audio bytes are
  ephemeral processing data, not a durable application archive. No hidden image
  description is stored for future turns.
- **Memories and personal context** — explicit shared/private facts plus bounded
  creator-private context that a user adds in an exact private conversation.
  They persist until deleted, cleared, expired, reset where authorized, or
  erased. Recall can be paused without deleting canonical content.
- **Derived summaries** — short summaries of conversations that expire with the
  messages they summarize and are removed when a group memory reset happens.
- **Safety and rate-limit records** — content-free records used to protect
  members. These hold no message content.
- **Coordination and audit records** — the bookkeeping that makes the product
  reliable and accountable. These hold no member content.
- **Private schedules** — an explicit timezone, bounded reminder/check-in rule,
  and reminder text where supplied. Check-ins require separate consent. Terminal
  details are reduced after the configured schedule-history period.

**How to get your data:** send `/export_my_data` to January. January records only a
non-secret request ID, then sends a short-lived single-use retrieval credential
at delivery time. Submit it in the Authorization header to the fixed retrieval
endpoint to receive a JSON package of your own data. The credential is never
stored by January or placed in a URL. Telegram may retain the delivered message as
an external platform copy. Group
administrators can request `/export_group_data` for group configuration and
stored group data (never member message content).

Subject exports include only that participant's exact-conversation explicit
memory, private personal context, record key/revision metadata, and recall
state. Group exports may include shared group explicit facts but never personal
context or participant recall policies.

Operating owners use the authenticated control plane for the content-free
deployment snapshot. This requires an explicit active `deployment_operator`
grant on an existing control-plane identity. Tenant owner/admin roles and
Telegram group-admin status do not grant deployment authority, and deployment
authority grants no tenant access. The control-plane POST response returns a
content-safe `202` while the existing governance worker materializes the
snapshot. Repeating the same POST and `X-Request-ID` after completion returns
one short-lived credential over HTTPS; only its hash persists, and retrieval
uses the same fixed Authorization-header endpoint.

**How to delete your data:** send `/forget_me` and confirm with
`/forget_me confirm` to erase your stored data; the message that you asked to
erase is removed from active use. Group administrators can reset group memory
with `/memory reset_group confirm`.

**How long data is kept:** the written retention schedule below is enforced
automatically for bounded categories and operator-configurable for the rest.

**Who owns encryption:** see the encryption-ownership matrix. In transit, the
operating owner provides HTTPS and the product requires it; secrets are
injected at the process boundary and never stored in the database, logs, or
audit. Application-level field encryption is not currently provided.

## Versioned data inventory (FR-01)

The machine-readable register lives in
`backend/app/domain/governance.py` (`DATA_INVENTORY`, version
`data-inventory-v6`); the deployment export embeds the same catalog. Any change
to what January stores updates the inventory in the same change.

- **conversations** — conversation identity, membership, and configuration
  state. Primary database; persists for the life of the conversation;
  configuration is immutable and revisioned. Controlled by the group
  administrator / operating owner.
- **participants** — member identity, preferences, opt-out and protection
  state. Primary database; persists; erasure leaves a content-free tombstone.
  Controlled by the subject.
- **messages** — raw message text and metadata. Primary database; bounded;
  automatically redacted after `raw_content_retention_days` (max 30).
  Controlled by the subject.
- **message_media** — exact-message attachment kind, caption, Telegram file
  references, bounded format/size/duration and processing state. Successful
  transcript text lives in messages with voice/audio provenance. Subject export
  includes only the subject's retained content/metadata; group/deployment export
  gains no member-content authority. Erasure clears references and captions,
  and source-message retention clears media at the original message deadline.
- **incoming_platform_updates** — raw platform update payloads. Primary
  database; bounded; automatically redacted after
  `raw_content_retention_days` (max 30). Controlled by the subject.
- **response_plans** — planned assistant responses and command replies.
  Primary database; bounded; automatically redacted. Controlled by the subject.
- **outbound_actions** — outbound delivery actions and payloads. Primary
  database; bounded; automatically redacted. Controlled by the subject.
- **telegram_command_jobs** — command jobs and their arguments. Primary
  database; bounded; arguments automatically redacted. Controlled by the
  subject.
- **conversation_feedback and conversation_feedback_events** — participant-
  owned helpful/unhelpful current state and immutable state-changing revisions,
  containing only authority identifiers, the closed value, revision, and
  timestamps. Subject export exposes only the requesting participant's
  structured values/history and target-response timestamps, without internal
  IDs or response text. Subject erasure or response retention hard-deletes the
  linked rows; group/deployment export exposes no feedback content.
- **participant_schedule_preferences** — exact private participant/conversation
  timezone and quiet-hour settings. Primary database; cleared on subject erasure.
- **proactive_schedules** — private bounded reminder/check-in rule, consent and
  reminder content. Primary database; active through its horizon, cancelled on
  request, cleared on erasure, and terminal timing/content redacted in bounded
  batches after `scheduler_history_retention_days`.
- **proactive_schedule_command_receipts** — content-free durable command
  idempotency/results. Coordination history controlled by the operating owner.
- **proactive_schedule_occurrences** — content-free delivery/recovery state while
  active; terminal schedule timestamps are reduced to tombstones after schedule
  retention. Subject export includes at most 100 exact-scope recent states.
- **explicit_memory_items** — explicit memory stored by members. Primary
  database; persists until deleted, expired, erased, or reset. Controlled by
  the subject / group administrator.
- **personal_context_items** — explicit creator-private context stored only in
  an exact private conversation. Primary database; persists until deleted,
  cleared, expired, or erased. Controlled only by the subject.
- **memory_recall_policies** — content-free exact participant/conversation
  recall authority and revision. Primary database; persists as revisioned
  authority/tombstone history. Controlled by the subject / operating owner.
- **memory_control_operations** — content-free durable command idempotency and
  bounded clear progress. Audit; persists as content-free operation history.
  Controlled by the operating owner.
- **memory_events** — content-free memory mutation audit. Audit; persists as
  content-free tombstone history. Controlled by the operating owner.
- **conversation_summaries** — derived conversation summaries. Primary
  database; expire at the earliest source-message deadline or on
  erasure/reset. Controlled by the subject / group administrator.
- **semantic_index_jobs** — coordination jobs for the derived semantic index.
  Coordination layer; ephemeral, content-free, rebuilt from explicit memory.
  Controlled by the operating owner.
- **semantic_index_collections** — derived-index collection registry. Derived
  index; rebuildable, content-free opaque points only. Controlled by the
  operating owner.
- **conversation_configuration_revisions** — immutable configuration and
  personality snapshots. Primary database; persists as immutable revision
  history. Controlled by the group administrator / operating owner.
- **safety_policy_decisions** — content-free safety decision records. Audit;
  bounded, governed separately from product-content retention. Controlled by
  the operating owner.
- **rate_limit_events** — content-free rate-limit event records. Audit;
  bounded. Controlled by the operating owner.
- **safety_review_items** — content-free moderation review queue. Audit;
  bounded by `safety_review_retention_days` (operator-configurable). Controlled
  by the operating owner.
- **control_tenants_and_operators** — canonical control-plane tenants,
  identities, tenant-scoped memberships, and compatibility bindings. Assistant
  and connection bindings are constrained to canonical core ownership and
  cannot reparent content. Audit; persists until operator-managed. Controlled
  by authorized tenant owners/admins and the operating owner according to role.
- **control_deployment_authorities** — durable, tenant-independent
  `deployment_operator` grants and revocations. Audit; persists until
  operator-managed. Controlled by an active deployment operator after the
  externally configured first-authority bootstrap.
- **control_deployment_authority_operations** — content-free request history
  that prevents concurrent or delayed grant/revoke replay from creating a
  second durable effect. Audit; persists until operator-managed.
- **control_group_revisions** — control-plane group configuration revisions.
  Audit; persists as immutable revision history. Controlled by the operating
  owner.
- **control_audit_events** — content-free control-plane audit trail. Audit;
  bounded by `governance_audit_retention_days`. Controlled by the operating
  owner.
- **governance_export_requests** — export request lifecycle (content-free).
  Audit; persists as content-free request history. Controlled by the operating
  owner.
- **governance_export_packages** — temporary single-use export packages
  (subject/group content). Primary database; expire after
  `governance_export_ttl_days`; single-use and cleared on retrieval. Controlled
  by the subject / group administrator.
- **governance_erasure_requests** — erasure request lifecycle and status
  (content-free). Audit; persists as content-free request history. Controlled
  by the operating owner.
- **governance_audit_events** — content-free governance audit trail. Audit;
  bounded by `governance_audit_retention_days`. Controlled by the operating
  owner.
- **operational_telemetry** — aggregated operational metrics. Operational
  telemetry; content-free aggregated counters. Controlled by the operating
  owner.
- **provider capabilities, routing, health, prices, and budgets** — immutable
  or revisioned non-secret operating configuration and content-free current
  projections. Controlled by authorized deployment operators or exact
  tenant-bound resource administrators; persists until operator-managed.
- **provider usage attempts, budget evaluations/reservations/windows, and work
  policy snapshots** — content-free provider-I/O attribution, usage quality,
  operational estimates, and conservative budget state. These records contain
  no prompt, response, memory, vector, credential, subject, or raw platform
  identity. Retention requires operating-owner approval and is not silently
  inherited from product-content erasure.

## Written retention schedule (FR-08)

One written schedule covers every category above. Automatically enforced
schedules are marked **enforced**; operator-configurable ones are marked
**operator-configurable**.

| Category | Retention | Enforcement |
| --- | --- | --- |
| messages, message_media, incoming_platform_updates, response_plans, outbound_actions, telegram_command_jobs | Content/references redacted after `raw_content_retention_days` (default 30, max 30); derived transcripts use original message age | enforced |
| conversation_summaries | Expire at the earliest source-message deadline; invalidated on erasure and group reset | enforced |
| explicit_memory_items, personal_context_items | Persist until deleted, cleared, expired, erased, or reset where authorized; expiry clears content/hash | enforced |
| memory_recall_policies, memory_control_operations | Content-free revision/idempotency history | operator-configurable |
| safety_review_items | Bounded by `safety_review_retention_days` (default 30) | operator-configurable |
| safety_policy_decisions, rate_limit_events | Bounded, governed separately from product-content retention | operator-configurable |
| control_audit_events, governance_audit_events | Bounded by `governance_audit_retention_days` (default 90) | enforced |
| governance_export_packages | Expire after `governance_export_ttl_days` (default 2); cleared on single-use retrieval | enforced |
| governance_export_requests, governance_erasure_requests, memory_events | Persist as content-free history | operator-configurable |
| proactive_schedules, proactive_schedule_occurrences | Active schedules persist through their bounded horizon; terminal content/timing is reduced after `scheduler_history_retention_days` (default 30) | enforced |
| participant_schedule_preferences | Persist until changed or subject erasure; no cross-conversation identity linkage | user-controlled |
| proactive_schedule_command_receipts | Content-free idempotency history | operator-configurable |
| conversation_feedback, conversation_feedback_events | No independent analytics retention; deleted on subject erasure or linked response-plan redaction | enforced |
| conversations, participants, conversation_configuration_revisions | Persist for the life of the conversation | operator-managed |
| control_tenants_and_operators, control_deployment_authorities, control_deployment_authority_operations, control_group_revisions | Persist until operator-managed | operator-managed |
| semantic_index_jobs, semantic_index_collections, operational_telemetry | Ephemeral/rebuildable/content-free | enforced |
| provider registry/routing/health/price/budget revisions and provider usage/reservation ledger | Content-free operating history; duration requires operating-owner approval | operator-configurable |

Schedule changes are configuration, never ad-hoc deletion.

## Backup and erasure boundary (FR-09)

- Backups are operator-managed copies for recovery and remain operator-managed.
- Erasure applies to live product state. Backup copies taken before an erasure
  may contain the erased data and must be purged by the operating owner under
  the declared backup-retention and purge policy.
- A backup containing redaction/privacy tombstones preserves those tombstones
  on restore. A backup taken before a later erasure cannot contain that later
  tombstone and must not be restored into production unless the operating owner
  first reapplies every post-backup erasure from an external operating record.
  This repository does not provide that external record; backup purge and
  post-restore reconciliation remain operating-owner controls.
- The derived index is rebuildable only from the reconciled canonical explicit
  memory state; it must remain stopped until that reconciliation completes.
- The backup procedure mandates encrypted backups and encrypted transport for
  any off-site copy (FR-10).
- The rehearsed backup/restore procedure (runbook) remains baseline and is not
  weakened.
