# SPEC-046 design handoff

Status: REVIEWED DESIGN — IMPLEMENTED AND LOCALLY VALIDATED

Date: 2026-10-09

## Baseline and observed problem

Clean HEAD/origin/main/remote main:
`private-source-checkpoint-omitted`. Prior GitHub Quality
37589375422 completed/success, main/push, exact SHA. Alembic has sole head
`0026_conversation_feedback`; migration NONE.

Baseline README measures 698 lines (`wc -l`), approximately the owner's 699.
It titles the retired identity, puts Quick Start after 390 lines, repeats voice/
feedback/memory details, carries internal candidate/status chronology and stale
roadmap commitments, and mixes contributor/API startup with guarded bot onboarding.
Current canonical compliance/encryption/governance/CONTRIBUTING copy and the
current product SPEC retain the old product name; the eval example uses an old
temporary filename. Two check-in templates also retain that identity.

## Chosen topology

January title/pitch and factual badges; What is January; Quick Start; grouped
Features; Architecture; Supported AI providers; Self-hosting; Documentation;
Development; Contributing; Security; Optional maintainer tooling; License.
Keep README under 400 lines and link deep details. No internal SPEC chronology,
invented screenshots, speculative roadmap or unsupported platform advertising.

Quick Start follows the existing Docker runbook: source, private template,
offline doctor, locally built setup image/init, operator configuration and
authenticated setup, polling start and qualified health checks. Setup is linked
explicitly rather than silently omitted; no automatic live/provider acceptance.

## Naming and runtime scope

The [approved spec](../../product/specs/SPEC-046-open-source-readme-january-brand-consolidation.md)
records the owner's name decision and four-way classification. Current public
identity changes; history does not. Keep one explicitly marked retired-name
history line in the current product SPEC and resolve its open naming question.
Arbitrary normalization, eligibility and media fixtures keep configured names
and mention offsets. Negative retired-name validation fixtures are intentional.

The check-in catalog is documented code-owned copy. No configured display-name
parameter exists at its caller. Correct only the two localized prefixes, like
existing `/start`/data-summary naming; do not thread identity dependencies or
change scheduling behavior. Test en/vi/auto and detail composition.

## Feature-claim review map

Each landing-page group is bounded by source and existing behavioral proof:

| Capability | Implemented source | Existing proof / guide |
| --- | --- | --- |
| Polling/webhook, durable inbox/outbox | runtime/telegram_poller.py; database/ingress.py | integration/test_ingress.py; self-hosted-quickstart.md |
| Selective replies/context | application/conversation.py; ambient.py | test_conversation_eligibility.py; test_conversation_context.py; test_ambient.py |
| Personality | application/personality.py; database/personality.py | test_personality.py; integration/test_personality_configuration.py |
| Structured planning | runtime/response_planning_worker.py | planning validator and provider tests |
| Five providers/routing/budgets | infrastructure/model_providers.py; governed_provider.py | test_model_providers.py; test_provider_governance.py |
| Memory/private context | application/memory.py; database/memory.py | test_memory.py; personal-context.md |
| Summaries | application/summary.py; runtime/conversation_summary_worker.py | test_summary.py; integration/test_conversation_summaries.py |
| Semantic memory | application/semantic_memory.py; runtime/semantic_memory_index_worker.py | test_semantic_memory.py; semantic-memory.md |
| Knowledge/RAG | application/knowledge.py; runtime/knowledge_index_worker.py | test_knowledge.py; integration/test_knowledge_rag.py |
| Scheduling/check-ins | application/scheduling.py; database/scheduling.py | test_scheduling.py; integration/test_scheduling_schema.py |
| Photo/audio | runtime/telegram_media.py | test_telegram_media.py; test_media_model_providers.py; telegram-media.md |
| Voice/TTS | database/voice.py; runtime/telegram_command_worker.py | integration/test_telegram_voice_tts.py; telegram-voice-tts.md |
| Feedback | database/feedback.py | integration/test_conversation_feedback.py; conversation-feedback.md |
| Reply UX/order | database/conversation.py; outbound_delivery_worker.py | integration/test_telegram_conversation_ux.py; test_conversation_ordering.py |
| Presence/reactions | application/presence.py; reactions.py | test_telegram_presence.py; test_telegram_reactions.py |
| Regeneration | application/regeneration.py; database/regeneration.py | test_telegram_regeneration.py; integration/test_telegram_regeneration.py |
| Multi-tenancy | database/models.py; authenticated HTTP control routes | integration/test_multi_tenant_model.py; multi-tenant-administration.md |
| Erasure/retention/export | database/retention.py; application/governance_export.py | integration/test_governance_schema.py; data-governance.md |
| Safety | application/safety.py | test_safety.py; test_safety_moderation.py; test_safety_recheck.py |
| Recovery/backup | existing recovery runtimes and backup tooling | reliability/backup-restore validators; backup-restore.md |
| Observability | application/observability/ | test_observability.py; test_observability_slos.py; observability.md |

Source paths above are under backend/app, tests under backend/tests, guides under
docs/runbooks unless stated otherwise. This is a review map, not a claim tests
have already run. Final handoff must cite observed executable results.

## Validation and historical continuity

Extend the existing public-release checker with offline structural/name/anchor
checks and isolated mutation tests; no new redundant validator or CI step.
Keep licensing checks unchanged and avoid prose snapshots. Inventory every
remaining retired-name hit with exact counts and classification.

Require verified README commands, static/Harness doctor, full unchanged workflow
order and required supplements, exact candidate/archive/modes and fresh shallow/
VCS-free Quality. No credentials, real provider/bot actions or source upload.
Historical specs, handoffs/completed records, audits and ADRs remain byte-identical
to baseline; Graphify source/pin/semantics stay unchanged.

## Handoff boundary

Final allowed status: APPROVED README / JANUARY BRAND CANDIDATE — INDEPENDENT
AUDIT PENDING, only after every mandatory gate passes. Independent OpenCode
audit is next. Do not commit, push, tag, create a release, change visibility,
start SPEC-047 or choose the first public version.

Private execution evidence is omitted from this public design record.
