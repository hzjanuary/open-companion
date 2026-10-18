# Product Docs

This directory contains current consumer-product behavior derived from real
accepted intent. Harness deliberately ships no fake product domains.

When a user provides a product specification, derive smaller living documents
here instead of keeping one growing specification as the operating manual. Name
files after actual product domains, such as `overview.md`, `billing.md`,
`permissions.md`, or `api-conventions.md`.

## Current Product Contract

January's [current product contract](SPEC.md), accepted specifications, code and
tests are consumer-owned truth. From SPEC-043 onward, the
[self-host deployment policy](self-hosted-deployment-profile.md) establishes
OPEN SOURCE / LOCAL-FIRST / SELF-HOSTED direction with optional single-VPS and
webhook, not a mandatory central production organization. Historical SPEC-041/
042 scope/evidence stays unchanged. Security, privacy, authority, migrations,
reliability and full Quality remain required. The owner selected [MIT](../../LICENSE)
during SPEC-044; historical license-pending records remain unchanged.

Setup starts in the [self-host quickstart](../runbooks/self-hosted-quickstart.md),
not historical specifications. SPEC-043 is complete at the self-host baseline;
see its historical handoff (private execution record omitted from this snapshot).
[Public release policy](../maintainers/release-process.md) separates a licensed
candidate, remote Quality, tagging and owner publication.
The SPEC-044 handoff (private execution record omitted from this snapshot) records the locally
validated licensed source candidate awaiting independent audit.

## Accepted Specifications

- [SPEC-047 First public release publication gate](specs/SPEC-047-first-public-release-publication-gate.md)
- [SPEC-046 Open-source README and January brand consolidation](specs/SPEC-046-open-source-readme-january-brand-consolidation.md)
- [SPEC-045 Optional maintainer knowledge graph and navigation](specs/SPEC-045-maintainer-knowledge-graph-codebase-navigation.md)

- [SPEC-044 Public open-source release and maintainer baseline](specs/SPEC-044-public-open-source-release-maintainer-baseline.md)
- [SPEC-043 Self-host distribution and first run](specs/SPEC-043-open-source-self-hosted-distribution-first-run.md)
- [SPEC-002 Database and Persistence](specs/SPEC-002-database-and-persistence.md)
- [SPEC-003 Telegram Platform Adapter](specs/SPEC-003-telegram-platform-adapter.md)
- [SPEC-004 Telegram Ingress, Queue, and Idempotency](specs/SPEC-004-telegram-ingress-queue-idempotency.md)
- [SPEC-005 Conversation Domain and Context](specs/SPEC-005-conversation-domain-and-context.md)
- [SPEC-006 LLM Provider and Response Planning](specs/SPEC-006-llm-provider-and-response-planning.md)
- [SPEC-007 Outbound Actions, Delivery, and Idempotency](specs/SPEC-007-outbound-actions-delivery-idempotency.md)
- [SPEC-008 Operator Bootstrap and End-to-End Demo](specs/SPEC-008-operator-bootstrap-end-to-end-demo.md)
- [SPEC-009 Personality Profiles and Group Configuration](specs/SPEC-009-personality-profiles-and-group-configuration.md)
- [SPEC-010 Telegram Administration Commands and User Preferences](specs/SPEC-010-telegram-administration-commands-and-user-preferences.md)
- [SPEC-011 Explicit Memory, Privacy, and Retention](specs/SPEC-011-explicit-memory-privacy-retention.md)
- [SPEC-012 Safety Policy and Distributed Rate Limiting](specs/SPEC-012-safety-policy-and-distributed-rate-limiting.md)
- [SPEC-013 Zalo Feasibility Spike and Capability Matrix](specs/SPEC-013-zalo-feasibility-spike-and-capability-matrix.md)
- [SPEC-014 Zalo Operator Verification Gate](specs/SPEC-014-zalo-operator-verification-gate.md)
- [SPEC-015 Telegram MVP Observability and Operational Telemetry](specs/SPEC-015-telegram-observability-and-operational-telemetry.md)
- [SPEC-016 Telegram Operational Reliability, Recovery, and Scale](specs/SPEC-016-telegram-operational-reliability-recovery-and-scale.md)
- [SPEC-017 Telegram Ambient Selective Participation](specs/SPEC-017-telegram-ambient-selective-participation.md)
- [SPEC-018 Telegram Conversation Summaries and Bounded Context Compression](specs/SPEC-018-telegram-conversation-summaries-and-context-compression.md)
- [SPEC-019 Explicit Memory Semantic Retrieval and Qdrant Derived Index](specs/SPEC-019-explicit-memory-semantic-retrieval-and-qdrant.md)
- [SPEC-020 Production Deployment, Secrets, and Runtime Operations](specs/SPEC-020-production-deployment-secrets-and-runtime-operations.md)
- [SPEC-021 Authenticated Operator and Group Administration Control Plane](specs/SPEC-021-authenticated-operator-and-group-administration-control-plane.md)
- [SPEC-022 Telegram Production Integration and Live Acceptance](specs/SPEC-022-telegram-production-integration-and-live-acceptance.md)
- [SPEC-023 Production Observability, SLOs, Alerting, and Incident Operations](specs/SPEC-023-production-observability-slos-alerting-and-incident-operations.md)
- [SPEC-024 Safety Moderation, Abuse Prevention, and User Protection](specs/SPEC-024-safety-moderation-abuse-prevention-and-user-protection.md)
- [SPEC-025 Data Governance, Encryption, Export, and Deletion Compliance](specs/SPEC-025-data-governance-encryption-export-and-deletion-compliance.md)
- [SPEC-026 Provider Routing, Cost Budgets, and Usage Governance](specs/SPEC-026-provider-routing-cost-budgets-and-usage-governance.md)
- [SPEC-027 User-Controlled Memory and Personal Context](specs/SPEC-027-user-controlled-memory-and-personal-context.md)
- [SPEC-028 Rich Telegram Media and Voice Interactions](specs/SPEC-028-rich-telegram-media-and-voice-interactions.md)
- [SPEC-029 Proactive Scheduling and Durable Social Participation](specs/SPEC-029-proactive-scheduling-and-durable-social-participation.md)
- [SPEC-030 Multi-Assistant / Multi-Tenant Product Model](specs/SPEC-030-multi-assistant-multi-tenant-product-model.md)
- [SPEC-032 AI Evaluation and Conversation Quality Framework](specs/SPEC-032-ai-evaluation-conversation-quality-framework.md)
- [SPEC-033 Telegram Knowledge Base / RAG](specs/SPEC-033-telegram-knowledge-base-rag.md)
- [SPEC-034 Telegram Reply Context and Ordered Delivery](specs/SPEC-034-telegram-reply-context-ordered-delivery.md)
- [SPEC-035 Telegram Presence and Response Feedback](specs/SPEC-035-telegram-presence-response-feedback.md)
- [SPEC-036 Telegram Response Editing and Regeneration](specs/SPEC-036-telegram-response-editing-regeneration.md)
- [SPEC-037 Telegram Reactions and Lightweight Social Feedback](specs/SPEC-037-telegram-reactions-lightweight-social-feedback.md)
- [SPEC-038 Explicit Telegram Voice Playback / TTS](specs/SPEC-038-telegram-explicit-voice-tts.md)
- [SPEC-039 Explicit Conversation Feedback and Quality Signals](specs/SPEC-039-explicit-conversation-feedback-quality-signals.md)
- [SPEC-040 Production Stabilization and Global CI Recovery](specs/SPEC-040-production-stabilization-global-ci-recovery.md)
- [SPEC-041 Telegram-first Release Readiness and Production Acceptance](specs/SPEC-041-telegram-first-release-readiness-production-acceptance.md)
- [SPEC-042 Production Promotion and Live Acceptance](specs/SPEC-042-production-promotion-live-acceptance.md)
- [SPEC-043 Open-Source Self-Hosted Distribution and First Run](specs/SPEC-043-open-source-self-hosted-distribution-first-run.md)
- [Data Governance, Export, and Deletion](data-governance.md)
- [Encryption Ownership](encryption-ownership.md)
- [Compliance Posture](compliance-posture.md)
- [Telegram Capabilities](telegram-capabilities.md)

## Roadmap State

SPEC-014 is `DEFERRED / BLOCKED_ON_EXTERNAL_PREREQUISITE` pending a dedicated
nonproduction Zalo OA/application. Its outstanding live checks do not block
the Telegram MVP. SPEC-001 through SPEC-022 are complete; SPEC-022 has been
approved and committed, with its live Telegram acceptance remaining an
externally gated operational step. SPEC-023 is implemented as an approved
candidate: the production observability contract (SLI catalog, SLO targets and
error budget over a rolling 28-day window, content-safe alert rules, and
incident operations) is declared in code and documentation with no schema
migration, pending Product Owner and operating-owner approval of the proposed
objectives and notification channels. SPEC-024 is implemented as an approved
candidate: the safety moderation, abuse prevention, and user protection
contract is enforced in the response-planning and outbound-delivery workers,
exposed through the `/safety`, `/protect`, and `/unprotect` commands and
content-free control-plane review endpoints, and backed by the additive
`0015_safety_moderation` migration and `safety_risk` alert rules; its threshold
objectives remain operating-owner approvals. SPEC-025 implementation is
Product Owner-authorized and the repository candidate is under final
validation: data governance, encryption, export, and deletion
compliance is enforced through the `/export_my_data`, `/export_group_data`,
and `/data_summary` commands, the credential-safe single-use retrieval endpoint,
the explicit tenant-independent `deployment_operator` authorization and
content-free deployment export, the additive
`0016_data_governance` migration, and the written retention schedule, with the
public-facing inventory and declarations in
[data-governance.md](data-governance.md), [encryption-ownership.md](encryption-ownership.md),
and [compliance-posture.md](compliance-posture.md); its retention and audit
schedules remain operating-owner approvals. SPEC-026 is the Product
Owner-approved product contract for versioned provider routing, content-safe
usage accounting, operational cost estimates, and pre-I/O deployment,
Assistant, and PlatformConnection budgets. Its implementation is complete and
committed at `eec38fe`; operating values and production rollout remain external
approvals. SPEC-027 is the Product Owner-approved contract for exact-scope,
explicit user-controlled memory and private-conversation personal context. Its
implementation is committed at `7011154`, followed by the `8bc2353` migration
bootstrap/governance hotfix; production rollout remains external. SPEC-028 is
Product Owner-approved and implementation-authorized for bounded ephemeral
photo/voice and supported audio processing, derived transcript governance and
enforced provider admission. Repository candidate is approved with Docker-backed
integration/migration/runtime verification pending, not production approval.
SPEC-029 has an approved Product Spec and validated repository candidate for
private, bounded reminders and separately consented deterministic check-ins.
SPEC-030 is the approved Product Spec and implemented candidate for canonical
tenant/Assistant/connection authority, scoped administration, deterministic
legacy backfill, and lifecycle fencing. Its isolated Docker validator proves
populated migration, contradiction refusal, database constraints, real
concurrency, and zero external calls after disable. Billing, self-service
organizations, assistant sharing/orchestration, Zalo, and SPEC-031 remain out
of scope. SPEC-032 is the approved and implemented offline AI evaluation and
conversation-quality framework: 130 synthetic Telegram-first scenarios execute
closed production-policy seams, hard failures cannot be averaged away, and
subjective rubrics remain `NOT_EVALUATED` without a future separately approved
judge. SPEC-033 is the approved, implemented repository candidate for
Assistant-scoped, PostgreSQL-authoritative knowledge with immutable document
revisions, content-free Qdrant payloads, mandatory post-search revalidation,
and a separate governed indexing worker. It adds migration
`0022_knowledge_base_rag`, remains disabled by default, and includes 13 new
offline knowledge cases. SPEC-033 was historically merged while deferred
Quality debt remained; SPEC-040 later closed that debt without rewriting the
original handoff. SPEC-034 adds migration
`0023_telegram_reply_ordered_delivery`, one authoritative direct reply reference,
and atomic ordered delivery of at most four text chunks plus one sticker. It
adds 12 deterministic hard eval scenarios and is an approved development
candidate whose historical global CI debt was later closed by SPEC-040.
SPEC-031 remains frozen on the unavailable Zalo prerequisite. SPEC-035 adds no
migration or durable state: it emits native
Telegram `typing` only after direct-response provider admission, refreshes with
one bounded execution-owned task, and stops before durable response completion.
Its failures are cosmetic and disable further presence for that execution. The
repository implementation retains its approved development chronology; the
shared historical Quality debt is closed.

SPEC-036 adds migration `0024_telegram_response_regeneration`, explicit
reply-only `/regenerate`, immutable root/parent/ordinal lineage capped at three,
current-context rebuilding, and mutually exclusive durable Telegram edit/new
presentation. Exact rejected edits can activate a normal send fallback;
ambiguous edits remain uncertain and never auto-send. Fourteen deterministic
offline cases extend the canonical suite. The implementation is a development
candidate whose original global-debt note remains historical; SPEC-040 closed
that debt and no deferred-CI exception remains.

SPEC-037 adds one deterministic, provider-free acknowledgement reaction after
terminal addressed planning. It creates no durable response work and accepts
crash omission rather than retrying a cosmetic Telegram call.

SPEC-038 adds migration `0025_telegram_voice_tts` and argument-free, reply-only
`/voice`. It synthesizes exactly one retained PostgreSQL-authoritative assistant
response through governed OpenAI TTS, persists one bounded short-lived OGG/Opus
delivery artifact, and reuses the existing durable outbound ambiguity/recovery
path. The feature is disabled by default, never creates new semantic content,
and adds 15 deterministic offline voice cases. It is an approved development
candidate whose historical Quality debt is closed by SPEC-040.

SPEC-039 adds migration `0026_conversation_feedback` and exact reply-only
`/feedback helpful|unhelpful`. It persists participant-owned current state and
immutable bounded history for the exact split/regenerated/voice-source response
plan, while excluding feedback from providers, adaptation, memory, knowledge,
summaries, and production evaluation truth. Subject export, erasure, retention,
backup, concurrency, and clean-candidate behavior have dedicated proof. It is
an approved development candidate whose historical Quality debt is closed.

SPEC-040 adds no product behavior and no migration. It preserves canonical
Tenant-to-Assistant authority and repairs stale integration-test setup that
depended on the conditional legacy migration row or prior test order. Its local
candidate passed repeated zero-failure reliability, every Quality step, fresh
and VCS-free clean-runner proof, and the unchanged 130-scenario eval baseline.
Historical SPEC-033 through SPEC-039 handoffs retain their chronology. Their
deferred global debt is closed by committed SPEC-040 baseline
`private-source-checkpoint-omitted` and successful GitHub Quality run
`36405527959`. The deferred-CI policy has ended.

SPEC-041 adds no product feature or migration. It defines the Telegram-first
repository release-readiness contract, complete configuration inventory,
production preflight, topology/startup/readiness, backup/restore and rollback,
security, staging, acceptance matrix, operator checklist, and external
prerequisite policy. Repository approval remains distinct from actual
production deployment and fresh live external acceptance. Its local candidate
was independently audited and committed at `8c8542d…` with successful exact-SHA
GitHub Quality `36721562006`; production and fresh live acceptance remain
operator-owned gates, not inherited proof.

SPEC-042 prepares the exact-source immutable promotion artifact, release record,
explicit operator approval/backup/config/readiness/monitoring gates and bounded
live procedures. It adds no product behavior or migration. No production/live
authority is granted by package preparation; the manifest records actual
availability and preserves NOT AUTHORIZED/NOT EXECUTED states.

## Update Rule

When behavior changes:

1. Update the affected product document when the expected behavior changed.
2. Update the active execution plan when complex work uses one.
3. Add a lasting decision only when future work must inherit a consequential
   product, architecture, data, security, compatibility, or validation choice.
4. Add or update executable proof that exercises the behavior.

Bounded changes do not require a story packet, proof-matrix row, or Harness CLI
mutation.
