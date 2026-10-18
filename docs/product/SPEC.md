# Product Specification — Multichannel Social AI Companion

**Current name:** January
**Historical working name:** Lumi (retired; retained here as naming history).
**Document:** `docs/product/SPEC.md`
**Version:** 0.1 Draft
**Status:** Awaiting product decisions
**Primary platform:** Telegram
**Future platform:** Zalo
**Primary language:** Vietnamese
**Primary delivery mechanism:** Codex using Repository Harness

Deployment-policy update, SPEC-043 (2026-10-01): future default is OPEN SOURCE /
LOCAL-FIRST / SELF-HOSTED, including local development/Compose and optional
single-VPS polling or public webhook. The operator is the person running it;
a central commercial organization, corporate approval/on-call, private registry,
paid provider and external monitoring are not prerequisites. The
[canonical self-host policy](self-hosted-deployment-profile.md) is the authority
for this chronological transition. Historical SPEC-041/042 and the stronger
production-promotion contract below remain correct for their original scope
and optional downstream use, not ordinary onboarding. Safety, privacy, tenant/
Assistant/connection authority, enforced governance, migrations, reliability,
backup/upgrade capability and full Quality remain mandatory. No new feature,
schema or migration is introduced. The owner later selected [MIT](../../LICENSE)
during SPEC-044. SPEC-043 is complete; its historical license-pending records
are preserved. Public release validation and publication remain separate. See the
SPEC-043 handoff (private execution record omitted from this snapshot).

---

## 1. Document Purpose

This document defines the product behavior, technical boundaries, architecture, delivery phases, user stories, acceptance criteria, and validation requirements for a scalable social AI companion.

This document is intended to become the authoritative product contract for Codex and human contributors.

The repository, its product documents, architecture decisions, code, tests, and observable runtime behavior are the system of record. Harness should not rely on hidden chat context or an external workflow database for ordinary development.

---

# 2. Confirmed Product Decisions

The following decisions have been confirmed by the product owner.

| Decision                     | Confirmed choice                             |
| ---------------------------- | -------------------------------------------- |
| Initial audience             | Groups of friends on Telegram                |
| Primary MVP problem          | Automatically respond to messages            |
| Highest engineering priority | Scalability and future extensibility         |
| Initial interaction style    | Natural, friendly, entertaining conversation |
| Initial social environment   | Private Telegram groups                      |
| Future channel               | Zalo                                         |
| Development agent            | Codex                                        |
| Development workflow         | Repository Harness                           |

---

# 3. Product Vision

January is a social AI companion that participates in messaging conversations like a natural member of the group.

Users can:

* Mention the assistant.
* Reply to the assistant.
* Ask questions.
* Chat casually.
* Joke with the assistant.
* Ask the assistant to mention another member.
* Receive text, emoji, and sticker responses.
* Configure how the assistant talks and behaves.

The long-term product should operate across Telegram and Zalo while preserving the same:

* Assistant identity.
* Personality.
* Conversation behavior.
* Memory policy.
* Safety policy.
* Observability.
* Administration model.

The messaging platforms must be treated as adapters around a platform-independent conversation engine.

---

# 4. Problem Statement

Most chatbots behave like command-based utilities:

* They wait for explicit commands.
* They answer too formally.
* They lack group context.
* They respond with long, unnatural messages.
* They do not know when to stay silent.
* They cannot maintain a consistent social personality.
* Their implementation is tightly coupled to one messaging platform.

The product must solve these problems by providing an assistant that:

1. Understands conversational context.
2. Responds selectively rather than mechanically.
3. Maintains a configurable personality.
4. Produces short, socially appropriate replies.
5. Supports Telegram-native actions such as replying, mentioning, and sending stickers.
6. Can later connect to Zalo without rewriting the conversation engine.

---

# 5. Product Principles

## 5.1 Natural Before Comprehensive

A short, relevant reply is preferred over a comprehensive but robotic answer.

Example:

```text
User:
@January Nam lại đi trễ rồi.

Preferred:
@Nam còn 30 giây để trình bày trước hội đồng nha 😌

Not preferred:
Dựa trên nội dung cuộc trò chuyện, có vẻ Nam đã đi trễ nhiều lần...
```

## 5.2 Silence Is a Valid Action

The assistant must be able to decide not to respond.

The response engine must support:

```json
{
  "should_respond": false,
  "reason_code": "conversation_does_not_require_assistant"
}
```

## 5.3 Platform Actions Must Be Structured

The language model must not directly call Telegram or Zalo APIs.

It produces a structured response plan. The application validates and executes that plan.

## 5.4 Platform Independence

Telegram-specific identifiers, sticker file IDs, webhook schemas, and API clients must remain inside the Telegram adapter.

The conversation engine must operate on internal types.

## 5.5 Privacy by Boundary

Information learned in a private conversation must not be surfaced in a group unless the user has explicitly allowed it or the information was already shared in that group.

## 5.6 Personality Is Configuration

Personality must not be implemented as a hard-coded prompt.

It must be represented by a typed, versioned configuration.

## 5.7 Observable Completion

A feature is complete only when its user-visible behavior has executable or observable proof. Harness records, checkboxes, or implementation descriptions are not sufficient on their own.

## 5.8 Evaluation Integrity

Conversation-quality regression evidence must keep objective hard contracts
separate from subjective quality judgments. Safety, privacy, tenant/Assistant
scope, provenance, authorization and forbidden side effects are hard gates and
cannot be averaged away. Canonical repository evaluation uses synthetic data,
closed deterministic drivers and no live provider or Telegram dependency.
Subjective rubrics remain explicitly unevaluated unless a separately governed
compatible judge is supplied.

## 5.9 Assistant Knowledge Is Separate Reference Data

SPEC-033 permits authenticated tenant operators to supply bounded plain-text or
Markdown reference material to one Assistant. PostgreSQL remains authoritative;
Qdrant stores only derived vectors and opaque IDs, and every hit is revalidated
before text enters the prompt as untrusted reference material. Assistant
knowledge never becomes user memory or personal context, and neither domain
creates, deletes, indexes, or authorizes the other.

## 5.10 Reply Context And Ordered Telegram Delivery

SPEC-034 treats an inbound Telegram reply ID only as a discovery hint. Model
context may include one bounded direct reference only after PostgreSQL proves
the same active tenant, Assistant, platform connection and conversation and
confirms the text remains retained and non-erased. The reference is untrusted
conversation data, never system policy, memory or knowledge.

Direct responses may reply to the canonical triggering message on their first
visible action; ambient and proactive messages remain replyless. Plain text is
split deterministically and losslessly into at most four 3,400 UTF-16-unit
chunks within a 13,600-unit logical limit. One response plan owns the atomic
sequence, and no later ordinal is claimable until all predecessors are
`delivered`. Only an exact deterministic Telegram missing-reply rejection may
trigger one replyless fallback; ambiguous delivery never does.

## 5.11 Telegram Presence And Response Feedback

SPEC-035 permits Telegram's native `typing` action only for an eligible
directly addressed response that has passed authority, safety, routing, budget,
rate, and concurrency admission and is about to perform provider I/O. Ambient
participation, proactive scheduling, deterministic commands, disabled/foreign
authority, provider denial, and terminal/recovered planning work emit none.

The initial signal is immediate. One execution-owned task may refresh every
four seconds, with five total calls and a twenty-second maximum lifetime. Each
refresh revalidates the exact planning lease and active lifecycle in a database
scope that closes before Telegram I/O. Every terminal/error/cancellation path
cancels and awaits the task before response-plan completion or delivery.

Presence is best effort and ephemeral. The first typed Telegram failure disables
further calls for that execution without changing provider generation or the
response. It creates no migration, durable retry, outbound action, memory,
knowledge, summary, or media state. The current Alembic head is
`0026_conversation_feedback`.

## 5.12 Explicit Conversation Feedback

SPEC-039 permits only exact reply commands `/feedback helpful` and `/feedback
unhelpful`. PostgreSQL resolves the retained local reply edge to the exact
delivered assistant response plan: split chunks share one logical target,
delivered edits use their regeneration plan, and voice presentation uses its
source response plan. Telegram quoted text is never authority.

Each canonical participant owns one current value and immutable state-changing
history per scoped response. Same-value repeats are `NO_CHANGE`; different
values serialize by a full-scope database lock and may advance through revision
10 only. Feedback produces a local deterministic acknowledgement and no model,
TTS, media, vector, reaction, presence, regeneration, memory, knowledge,
summary, configuration, safety, route, or budget work. It never changes
production evaluation truth or future model context.

Subject export contains only that participant's structured values, revisions,
and timestamps. Subject erasure and linked response retention hard-delete the
rows. Group/deployment export and `deployment_operator` receive no feedback
content or inspection endpoint.

---

# 6. Platform Constraints

## 6.1 Telegram

The official Telegram Bot API supports:

* Receiving updates through webhooks.
* Sending text messages.
* Replying to messages.
* Mentioning users.
* Sending static, animated, and video stickers.
* Participating in private chats, groups, and supergroups.

Telegram group bots use Privacy Mode by default. In that mode, a bot mainly receives commands, messages directed to it, inline interactions, and replies to the bot. A bot that must observe ordinary group messages must be configured appropriately, such as by disabling Privacy Mode or operating with relevant administrator permissions.

Therefore, the product must distinguish between:

```text
Platform visibility:
What messages Telegram delivers to the bot.

Response policy:
Which delivered messages the assistant chooses to answer.
```

These are separate settings.

## 6.2 Zalo

Zalo Developers currently exposes Official Account capabilities covering messaging, webhooks, and Group Management Features—GMF.

Zalo is not part of the first MVP.

Before Zalo implementation, a dedicated technical feasibility phase must verify:

* Supported group conversation types.
* Incoming group message events.
* Outgoing group messages.
* Member mention behavior.
* Sticker or media support.
* Token lifecycle.
* Rate limits and quotas.
* Official Account review requirements.
* Restrictions on automated or conversational use.

No production feature may depend on undocumented personal-account automation.

---

# 7. Product Scope

## 7.1 MVP Scope

The initial MVP will support Telegram groups of friends.

Included:

* Telegram webhook integration.
* Direct message support.
* Group message support.
* Mention and reply detection.
* Automatic response selection.
* Text responses.
* Reply-to-message behavior.
* User mentions in outgoing responses.
* Sticker responses.
* One default personality.
* Per-group personality configuration.
* Recent conversation context.
* Basic group memory.
* Basic safety rules.
* Rate limiting.
* Idempotent webhook processing.
* Structured logs and basic metrics.
* Bot administration through commands.
* LLM provider abstraction.

## 7.2 Post-MVP Scope

* Personality web dashboard.
* Long-term semantic memory.
* User-controlled memory interface.
* Advanced relationship modeling.
* Multiple LLM providers with routing.
* Voice messages.
* Image understanding.
* Image generation.
* Scheduled messages.
* Proactive group participation.
* Zalo OA integration.
* Multi-tenant SaaS management.
* Subscription and billing.

## 7.3 Explicitly Out of Scope for MVP

* Automation through a normal Zalo personal account.
* Public Telegram community moderation.
* Autonomous direct messaging to users.
* Full social network user profiling.
* Unlimited storage of all conversation history.
* Personality marketplace.
* End-user mobile application.
* Custom model training.
* Romantic or adult companion behavior.
* Unrestricted insulting or harassment-oriented “roast mode.”

---

# 8. Primary Users

## 8.1 Group Member

A member of a Telegram friend group who interacts with the assistant naturally.

The member can:

* Mention the assistant.
* Reply to it.
* Ask questions.
* Joke with it.
* Request a sticker.
* Ask what the assistant remembers.
* Ask the assistant not to mention or tease them.

## 8.2 Group Administrator

The person who adds and configures the bot.

The administrator can:

* Activate the assistant in the group.
* Select the response mode.
* Configure personality.
* Set humor and teasing limits.
* Set response frequency.
* Enable or disable stickers.
* Reset group memory.
* Pause the assistant.

## 8.3 Product Operator

The technical operator responsible for the deployment.

The operator can:

* Configure platform credentials.
* Configure LLM providers.
* Inspect health and readiness.
* Review failures.
* Monitor latency, token usage, and rate limits.
* Disable a provider or platform connection.

---

# 9. Core Interaction Modes

Each conversation must have a `response_mode`.

## 9.1 `mention_only`

The assistant responds only when:

* Its Telegram username is mentioned.
* A command explicitly targets the bot.
* A user replies to a bot message.

Recommended for initial testing.

## 9.2 `mention_and_name`

The assistant responds when:

* Mentioned.
* Replied to.
* Its configured display name appears in the text.

## 9.3 `ambient_selective`

The assistant receives general group messages and decides whether it has a socially useful response.

The assistant should normally remain silent.

## 9.4 `paused`

The assistant processes only administrator commands and does not participate.

## Proposed MVP Default

```text
mention_and_name
```

`ambient_selective` should be implemented behind a feature flag after mention-based behavior is stable.

The product must not initially implement an `answer_every_message` mode because it would create spam, excessive cost, conversational loops, and poor group experience.

---

# 10. Functional Requirements

## FR-001 — Telegram Connection

The system shall allow an operator to connect a Telegram bot using a secure bot token.

Requirements:

* Tokens are loaded from secrets or encrypted configuration.
* Tokens must not be logged.
* The connection can be enabled or disabled.
* Startup validates bot identity using the Telegram API.
* Invalid credentials cause readiness failure for the Telegram integration without exposing the token.

---

## FR-002 — Telegram Webhook

The system shall receive Telegram updates through an HTTPS webhook.

Requirements:

* Validate the Telegram webhook secret.
* Parse the payload at the interface boundary.
* Reject invalid payloads.
* Record the Telegram `update_id`.
* Deduplicate previously processed updates.
* Acknowledge valid webhook requests without waiting for LLM completion.
* Submit message processing to an asynchronous worker.
* Preserve per-conversation message ordering where required.

Telegram payloads are unknown external input and must be parsed into typed internal objects before entering application or domain logic. This follows the Harness parse-first boundary rule.

---

## FR-003 — Event Normalization

All platform messages shall be converted into a platform-independent event.

Synthetic example (all identifiers, names and message content are fabricated):

```json
{
  "event_id": "evt_uuid",
  "platform": "telegram",
  "platform_update_id": "123456",
  "conversation": {
    "platform_id": "-100123456",
    "type": "group"
  },
  "sender": {
    "platform_user_id": "998877",
    "display_name": "Synthetic Member",
    "username": "synthetic_member"
  },
  "message": {
    "platform_message_id": "842",
    "type": "text",
    "text": "@January hôm nay ăn gì?",
    "mentions_assistant": true,
    "replies_to_assistant": false
  },
  "received_at": "ISO-8601 timestamp"
}
```

Platform payload objects must not be passed into the conversation engine.

---

## FR-004 — Message Persistence

The system shall persist eligible incoming and outgoing messages.

Minimum fields:

* Internal message ID.
* Platform.
* Platform message ID.
* Conversation ID.
* Sender identity.
* Message type.
* Text content when applicable.
* Reply target.
* Mention metadata.
* Direction.
* Processing status.
* Creation timestamp.

The system shall support retention policies and deletion.

---

## FR-005 — Response Eligibility

The system shall determine whether a message is eligible for assistant processing.

Eligibility checks include:

* Platform connection enabled.
* Conversation enabled.
* Sender is not the assistant itself.
* Event has not already been processed.
* Response mode permits the interaction.
* User or group is not rate limited.
* Message type is supported.
* Message does not create a known bot loop.
* Group is not paused.

The eligibility decision must occur before an expensive LLM request.

---

## FR-006 — Conversation Context

The system shall assemble relevant context for each response request.

Context may include:

* Current incoming message.
* Reply chain.
* Recent messages from the same conversation.
* Group settings.
* Active personality.
* Relevant group memories.
* Relevant user preferences.
* Safety instructions.
* Platform action capabilities.

Context must have a configurable token budget.

Old messages must be truncated or summarized before exceeding the configured budget.

---

## FR-007 — Personality Profiles

The system shall represent personality using typed configuration.

Example:

```yaml
name: January
version: 1

identity:
  role: friendly_group_companion
  primary_language: vi
  self_reference: mình

communication:
  default_length: short
  formality: casual
  humor_level: 0.70
  teasing_level: 0.35
  emoji_frequency: 0.30
  sticker_frequency: 0.15

behavior:
  response_mode: mention_and_name
  use_member_names: true
  use_inside_jokes: false
  ask_follow_up_questions: sometimes

boundaries:
  allow_sensitive_teasing: false
  stop_teasing_on_request: true
  reveal_private_memory_in_groups: false
```

Requirements:

* Personality profiles are versioned.
* Each group references an active profile version.
* Updating a personality does not require redeployment.
* Personality values are validated.
* Prompt generation is deterministic for a given personality version.

---

## FR-008 — LLM Provider Abstraction

The conversation engine shall depend on a platform-independent `ModelProvider` interface.

Example conceptual interface:

```python
class ModelProvider(Protocol):
    async def generate_response(
        self,
        request: ConversationGenerationRequest,
    ) -> ConversationGenerationResult:
        ...
```

The interface shall support:

* Provider identifier.
* Model identifier.
* Timeout.
* Retry policy.
* Structured output.
* Usage accounting.
* Provider error classification.
* Optional fallback provider.

Provider-specific SDK objects must not escape the infrastructure layer.

---

## FR-009 — Structured Response Plan

The LLM shall produce a structured response plan instead of directly producing platform actions.

Example:

```json
{
  "should_respond": true,
  "reason_code": "assistant_was_mentioned",
  "text": "Đi ăn cơm tấm đi, câu này mình không cần suy nghĩ lâu 😌",
  "reply_to_message_id": "internal-message-uuid",
  "mentions": [
    {
      "participant_id": "internal-participant-uuid"
    }
  ],
  "sticker_intent": null,
  "confidence": 0.91
}
```

Requirements:

* Output is schema validated.
* The model must not generate raw Telegram user IDs.
* The model must not generate Telegram sticker file IDs.
* All referenced internal IDs must exist in the supplied context.
* Unknown action types are rejected.
* Invalid output may be retried once with a correction prompt.
* Repeated invalid output produces a safe text fallback or no response.

---

## FR-010 — Response Policy

The application shall apply deterministic policy after LLM generation.

Policy checks include:

* Maximum response length.
* Allowed mention targets.
* Allowed sticker intent.
* Group response frequency.
* User opt-out settings.
* Safety restrictions.
* Platform capability.
* Rate limit.
* Duplicate response prevention.

The policy layer may:

* Approve the response.
* Remove an invalid mention.
* Remove the sticker.
* Shorten or reject the response.
* Replace the response with a safe fallback.
* Choose not to respond.

---

## FR-011 — Text Response

The system shall send validated text responses to Telegram.

Requirements:

* Support plain text.
* Support replies to specific messages.
* Preserve the originating group or topic.
* Escape or construct formatting safely.
* Store the outgoing platform message ID.
* Record failure details without leaking secrets.
* Avoid sending the same response twice after retry.

---

## FR-012 — User Mentions

The system shall mention users only through validated participant identities.

Requirements:

* Resolve the internal participant to a Telegram identity.
* Prefer `@username` when available.
* Support Telegram-compatible mention entities when allowed.
* Never invent usernames.
* Never mention a person who is not part of the conversation context.
* Respect per-user mention opt-out.

---

## FR-013 — Sticker Responses

The assistant shall select stickers through semantic intent.

Supported initial intents:

```text
laugh
celebrate
awkward
suspicious
facepalm
support
sad
angry_cute
confused
```

The LLM returns:

```json
{
  "sticker_intent": "suspicious"
}
```

The sticker service resolves this to a platform asset.

Requirements:

* Stickers have internal IDs.
* Telegram `file_id` values remain inside the Telegram infrastructure adapter.
* Administrators can disable sticker responses.
* Sticker frequency follows personality configuration.
* The system must not send text and a sticker separately when policy selects only one.
* Sticker send failures may fall back to text.

The official Telegram Bot API supports sending static, animated, and video stickers.

---

## FR-014 — Bot Commands

Initial commands:

```text
/start
/help
/status
/personality
/mode
/quiet
/resume
/stickers
/memory
/forget
/forget_me
```

Administrator-only commands:

```text
/mode
/quiet
/resume
/personality set
/stickers enable
/stickers disable
/memory reset_group
```

Authorization must be enforced in application logic, not only through command visibility.

---

## FR-015 — Short-Term Memory

The system shall provide recent conversational memory.

Initial implementation:

* Persist recent messages.
* Load a configurable number of recent messages.
* Include at most one authoritative, bounded direct reply reference.
* Exclude deleted or disallowed messages.
* Keep memory isolated by conversation.

A private chat and a group chat are different memory scopes.

---

## FR-016 — Long-Term Memory

Long-term semantic memory is not required for the first usable Telegram response.

The architecture must allow it later through a `MemoryRepository` abstraction.

Future memory types:

* User preference.
* Group fact.
* Inside joke.
* Conversation summary.
* Explicitly remembered fact.

Each memory item must include:

* Scope.
* Source.
* Confidence.
* Created timestamp.
* Expiration policy.
* Visibility policy.
* Deletion state.

---

## FR-017 — User Privacy Controls

A user shall be able to:

* Ask what the assistant remembers.
* Ask the assistant to forget a memory.
* Ask the assistant to delete their stored profile.
* Disable mentions.
* Disable teasing directed at them.

The assistant must acknowledge a successful privacy action without exposing hidden internal data.

---

## FR-018 — Safety

The assistant shall reject or avoid behavior that creates:

* Harassment.
* Hate or identity attacks.
* Sexual content involving minors.
* Encouragement of self-harm.
* Disclosure of private information.
* Targeted humiliation.
* Persistent teasing after a user opts out.
* Dangerous instruction execution.

Initial teasing rules:

* No teasing based on body, disability, race, religion, gender, sexuality, medical condition, financial hardship, or private trauma.
* No repeated targeting of one user.
* Stop immediately after an opt-out.
* Default teasing level must be low or medium.
* “Roast mode” is not part of MVP.

---

## FR-019 — Rate Limiting

The system shall support rate limits by:

* Platform connection.
* Conversation.
* User.
* LLM provider.
* Deployment.

Rate limit values must be configuration, not hard-coded product policy.

When limited, the system may:

* Remain silent.
* Return a short cooldown message.
* Record a metric.
* Avoid calling the LLM.

---

## FR-020 — Administration

MVP administration shall be available through:

* Environment and secret configuration.
* Telegram administrator commands.
* Database-backed group settings.

A web dashboard is deferred.

---

# 11. Non-Functional Requirements

## NFR-001 — Scalability

The application must support horizontal scaling.

Requirements:

* Webhook API instances are stateless.
* Durable state is stored outside process memory.
* Work is dispatched asynchronously.
* Duplicate Telegram updates are safe.
* Processing can be retried.
* Outgoing actions are idempotent.
* Conversation ordering is preserved where necessary.
* Provider concurrency can be controlled centrally.

## NFR-002 — Availability

Failure of one LLM request must not crash the webhook service.

The system must support:

* Provider timeout.
* Retryable provider errors.
* Non-retryable provider errors.
* Queue retry.
* Dead-letter handling.
* Health endpoint.
* Readiness endpoint.

## NFR-003 — Latency Targets

Proposed initial service objectives:

| Operation                                     | Target              |
| --------------------------------------------- | ------------------- |
| Valid webhook acknowledgement                 | p95 under 500 ms    |
| Mention response without provider degradation | p95 under 8 seconds |
| Non-LLM command response                      | p95 under 1 second  |
| Health check                                  | p95 under 250 ms    |

These are proposed product targets, not claims about an existing implementation.

## NFR-004 — Security

* Secrets must not be committed.
* Webhook requests must be authenticated.
* Database access must use least privilege.
* Logs must redact tokens and sensitive headers.
* Administrative commands must verify Telegram identity and group role.
* External input must be parsed before entering application logic.
* Prompt injection must not be allowed to create arbitrary platform actions.

## NFR-005 — Observability

Every request or processing operation should emit structured logs containing:

* Timestamp.
* Level.
* Request ID.
* Correlation ID.
* Conversation ID when known.
* Message ID when known.
* Action.
* Duration.
* Status.
* Error classification.

Audit records and operational logs are separate concepts.

Metrics should include:

* Webhooks received.
* Duplicate updates.
* Eligible messages.
* Responses sent.
* Silent decisions.
* LLM requests.
* Provider latency.
* Invalid structured outputs.
* Telegram send failures.
* Token usage.
* Estimated provider cost.
* Rate-limit events.

## NFR-006 — Testability

Domain and application behavior must be testable without Telegram, an actual LLM, or a network connection.

All external dependencies require interfaces and test doubles.

## NFR-007 — Maintainability

The preferred dependency direction is:

```text
domain
  <- application
      <- infrastructure
          <- interface
              <- runtime surfaces
```

Inner layers must not depend on Telegram SDKs, databases, web frameworks, or LLM SDKs. This follows the Harness consumer architecture guidance.

---

# 12. Proposed Technical Architecture

## 12.1 Initial Deployment Shape

Use a modular monolith with independently scalable processes.

```text
Telegram
   |
   v
Webhook API
   |
   v
Event Queue
   |
   v
Conversation Worker
   |
   +--> PostgreSQL
   +--> Redis
   +--> LLM Provider
   |
   v
Outbound Action Queue
   |
   v
Telegram Sender
```

A modular monolith is recommended before microservices because:

* Domain boundaries can still be enforced.
* Local development is simpler.
* Codex sees the complete behavior in one repository.
* Deployment is easier.
* Individual processes can still scale horizontally.
* Modules can later be extracted when runtime evidence justifies it.

## 12.2 Proposed Stack

This stack is provisional and requires product-owner approval.

| Surface                           | Proposed technology                                          |
| --------------------------------- | ------------------------------------------------------------ |
| Backend language                  | Python                                                       |
| HTTP framework                    | FastAPI                                                      |
| Validation                        | Pydantic                                                     |
| Database                          | PostgreSQL                                                   |
| ORM and migrations                | SQLAlchemy async and Alembic                                 |
| Queue and short-term coordination | Redis                                                        |
| Worker                            | Redis-backed worker abstraction                              |
| Object storage                    | S3-compatible storage when needed                            |
| Vector memory                     | Qdrant, deferred                                             |
| Admin frontend                    | Next.js, deferred                                            |
| Containerization                  | Docker                                                       |
| Local composition                 | Docker Compose                                               |
| Testing                           | pytest                                                       |
| Lint and formatting               | Ruff                                                         |
| Type checking                     | mypy                                                         |
| CI                                | GitHub Actions                                               |
| Observability                     | Structured logs and OpenTelemetry-compatible instrumentation |

## 12.3 Core Modules

```text
backend/app/
├── domain/
│   ├── assistants/
│   ├── conversations/
│   ├── identities/
│   ├── personalities/
│   ├── responses/
│   ├── stickers/
│   ├── memory/
│   └── safety/
│
├── application/
│   ├── commands/
│   ├── queries/
│   ├── handlers/
│   ├── policies/
│   └── ports/
│
├── infrastructure/
│   ├── database/
│   ├── queue/
│   ├── llm/
│   ├── telegram/
│   ├── zalo/
│   ├── memory/
│   └── observability/
│
├── interface/
│   ├── http/
│   ├── webhook/
│   ├── dto/
│   ├── middleware/
│   └── commands/
│
└── main.py
```

This is a target dependency shape, not a requirement to create every directory before its first real use.

---

# 13. Domain Model

## 13.1 Assistant

```text
Assistant
- id
- name
- status
- default_personality_profile_id
- created_at
- updated_at
```

## 13.2 PlatformConnection

```text
PlatformConnection
- id
- assistant_id
- platform
- external_bot_id
- encrypted_credentials_reference
- status
- configuration
- created_at
- updated_at
```

## 13.3 Conversation

```text
Conversation
- id
- platform_connection_id
- platform_conversation_id
- conversation_type
- title
- status
- response_mode
- personality_profile_version_id
- settings
- created_at
- updated_at
```

## 13.4 Participant

```text
Participant
- id
- conversation_id
- platform_user_id
- username
- display_name
- role
- mention_allowed
- teasing_allowed
- created_at
- updated_at
```

## 13.5 Message

```text
Message
- id
- conversation_id
- participant_id
- platform_message_id
- direction
- message_type
- text
- reply_to_message_id
- metadata
- processing_status
- created_at
```

## 13.6 PersonalityProfile

```text
PersonalityProfile
- id
- assistant_id
- name
- active_version
- created_at
- updated_at
```

## 13.7 PersonalityProfileVersion

```text
PersonalityProfileVersion
- id
- profile_id
- version
- configuration
- prompt_template_version
- created_at
```

## 13.8 ResponseAttempt

```text
ResponseAttempt
- id
- incoming_message_id
- provider
- model
- response_plan
- outcome
- latency_ms
- token_usage
- error_class
- created_at
```

## 13.9 OutboundAction

```text
OutboundAction
- id
- response_attempt_id
- action_type
- payload
- idempotency_key
- status
- platform_message_id
- retry_count
- created_at
- completed_at
```

## 13.10 StickerAsset

```text
StickerAsset
- id
- assistant_id
- intent
- platform
- platform_asset_reference
- enabled
- weight
- metadata
```

## 13.11 MemoryItem

```text
MemoryItem
- id
- scope_type
- scope_id
- subject_participant_id
- memory_type
- content
- source_message_id
- visibility
- confidence
- expires_at
- deleted_at
- created_at
```

## 13.12 SafetyEvent

```text
SafetyEvent
- id
- conversation_id
- message_id
- category
- action
- metadata
- created_at
```

---

# 14. Internal Application Flow

```text
1. Receive Telegram webhook.
2. Authenticate webhook.
3. Parse update into Telegram DTO.
4. Deduplicate update.
5. Persist raw metadata where permitted.
6. Normalize to IncomingConversationEvent.
7. Evaluate inexpensive eligibility rules.
8. Enqueue eligible event.
9. Load conversation and participant settings.
10. Load recent context.
11. Build generation request.
12. Call selected LLM provider.
13. Parse structured response plan.
14. Validate response references.
15. Apply safety and conversation policy.
16. Create outbound actions.
17. Send actions through Telegram adapter.
18. Persist result.
19. Emit logs and metrics.
```

---

# 15. Failure Handling

## 15.1 Duplicate Webhook

Expected behavior:

* Return success.
* Do not process twice.
* Record duplicate metric.

## 15.2 LLM Timeout

Expected behavior:

* Retry only according to configured policy.
* Do not block the webhook request.
* Optionally send no response.
* Record provider timeout.

## 15.3 Invalid Structured Output

Expected behavior:

* Retry parsing or generation once.
* Use safe fallback when configured.
* Never execute unvalidated platform actions.

## 15.4 Telegram Rate Limit

Expected behavior:

* Read retry information when available.
* Reschedule the outbound action.
* Preserve idempotency.
* Prevent rapid retry loops.

## 15.5 Worker Crash

Expected behavior:

* Unacknowledged work becomes available for retry.
* Previously completed outbound actions are not duplicated.

## 15.6 Database Unavailable

Expected behavior:

* Readiness reports failure.
* Webhook processing must not falsely claim durable acceptance when persistence is required.
* Recovery behavior must be documented and tested.

---

# 16. Success Metrics

## Product Metrics

* Percentage of mentions receiving a successful response.
* User reaction rate.
* Group retention after seven days.
* Percentage of responses followed by another user message.
* Percentage of assistant messages deleted by administrators.
* Per-group quiet or disable rate.
* Sticker engagement rate.

## Quality Metrics

* Invalid response-plan rate.
* Duplicate outgoing message rate.
* Incorrect mention rate.
* Safety-policy violation rate.
* User opt-out compliance rate.
* Private-memory leakage incidents.

## Reliability Metrics

* Webhook success rate.
* Worker success rate.
* Telegram send success rate.
* LLM provider success rate.
* Response latency.
* Queue depth.
* Retry and dead-letter counts.

## Initial MVP Quality Gates

* No duplicate response in idempotency tests.
* No raw provider or Telegram payload in domain services.
* No model-generated platform ID executed without validation.
* No private-chat memory included in group context.
* All administrator commands verify authorization.
* All required tests and static checks pass.

---

# 17. Delivery Plan

This project requires durable planning because it spans multiple sessions, has meaningful dependencies, and must remain resumable by Codex. Harness recommends one evolving plan under `docs/plans/active/` for this type of work.

The historical MVP execution record is omitted from this public snapshot.
For new durable work, create one task-specific plan under `docs/plans/active/`
using `docs/templates/exec-plan.md` and the current `docs/WORKFLOW.md`.

The active plan should contain outcome, context, scope, approach, risks, progress, decisions, validation, and final result, following the Harness execution-plan template.

---

# 18. Implementation Phases

## Phase 0 — Repository and Harness Foundation

### Outcome

Codex can enter the repository, identify authoritative documents, run validation, and implement bounded tasks without relying on chat history.

### User Story

**As a product owner,**
I want product intent and engineering rules stored in the repository,
so that Codex can work consistently across sessions.

### Scope

* Install Repository Harness.
* Add compact `AGENTS.md`.
* Add product SPEC.
* Add architecture document.
* Add documentation index.
* Add active MVP execution plan.
* Add initial architecture decisions.
* Define validation commands.
* Create application skeleton.
* Configure CI.

### Acceptance Criteria

* `AGENTS.md` points to the authoritative workflow and documents.
* `docs/product/SPEC.md` contains this accepted specification.
* `docs/ARCHITECTURE.md` defines dependencies and runtime boundaries.
* Durable work has an execution plan under the current workflow. The original
  private MVP execution record is omitted from this snapshot.
* Repository startup, test, lint, and type-check commands are documented.
* CI runs the required quality checks.
* A fresh Codex session can identify the next task from repository state.
* No optional Harness SQLite control plane is required for ordinary implementation.

---

## Phase 1 — Backend and Telegram Foundation

### Outcome

The application receives Telegram webhook events reliably and can send a deterministic response without an LLM.

### User Story 1

**As a Telegram group administrator,**
I want to connect the bot to a group,
so that the group can interact with the assistant.

### User Story 2

**As an operator,**
I want webhook updates processed idempotently,
so that Telegram retries do not create duplicate responses.

### Scope

* Backend bootstrap.
* Configuration and secret loading.
* Structured logging.
* PostgreSQL foundation.
* Redis foundation.
* Telegram adapter.
* Webhook endpoint.
* Webhook authentication.
* Event DTO and normalization.
* Update deduplication.
* Conversation and participant persistence.
* Deterministic `/start`, `/help`, and `/status`.
* Health, readiness, and liveness.
* Docker Compose.
* Integration tests with captured Telegram fixtures.

### Acceptance Criteria

* Valid webhook fixture returns success.
* Invalid secret is rejected.
* Invalid payload is rejected without entering application logic.
* The same `update_id` submitted twice produces one processing operation.
* `/help` produces one Telegram response.
* Outbound response uses an idempotency key.
* Health and readiness distinguish process health from dependency readiness.
* Tests run without calling the real Telegram API.
* Telegram SDK or HTTP types do not appear in domain modules.
* Required lint, type-check, unit, and integration checks pass.

---

## Phase 2 — Conversation and LLM Response Engine

### Outcome

The assistant generates natural Vietnamese responses for eligible Telegram messages.

### User Story 1

**As a group member,**
I want the assistant to answer when I mention it,
so that interacting with it feels immediate and natural.

### User Story 2

**As a group member,**
I want responses to consider recent messages,
so that the assistant understands the conversation.

### Scope

* Eligibility policy.
* Conversation context builder.
* Default personality.
* Model provider abstraction.
* Initial provider implementation.
* Structured response-plan schema.
* Prompt construction.
* Output validation.
* Response policy.
* Text sending.
* Reply-to-message support.
* Provider usage records.
* Timeout and retry handling.

### Acceptance Criteria

* A mention produces a response-plan request.
* An unrelated message in `mention_only` mode does not call the LLM.
* Recent conversation messages are included in correct order.
* Messages from another group are never included.
* LLM output must conform to the response-plan schema.
* Invalid IDs in model output are rejected.
* Invalid output does not produce a Telegram action.
* Provider timeout does not crash webhook processing.
* A successful response is persisted with provider and latency metadata.
* End-to-end test proves: Telegram fixture → normalized event → model stub → Telegram send stub.

---

## Phase 3 — Personality and Social Actions

### Outcome

The assistant behaves consistently and can reply, mention users, and send stickers naturally.

### User Story 1

**As a group administrator,**
I want to configure the assistant’s personality,
so that its behavior fits our group.

### User Story 2

**As a group member,**
I want the assistant to mention the right person,
so that its replies feel native to group conversation.

### User Story 3

**As a group member,**
I want the assistant to sometimes respond with a sticker,
so that conversations feel more playful.

### Scope

* Versioned personality profiles.
* Personality validation.
* Group personality assignment.
* Mention resolution.
* Mention opt-out.
* Sticker intent model.
* Telegram sticker registry.
* Sticker action policy.
* Personality commands.
* Sticker enable and disable commands.
* Basic teasing safety.
* Response length and frequency controls.

### Acceptance Criteria

* Group A and Group B can use different personality versions.
* Changing personality configuration does not require deployment.
* Model output cannot mention a participant absent from supplied context.
* A participant without a usable Telegram identity is not incorrectly mentioned.
* `sticker_intent` resolves through the sticker registry.
* Model output never contains executable Telegram `file_id` values.
* Disabled stickers are never sent.
* A user who disables teasing is excluded from teasing targets.
* Personality version used for each response is recorded.
* End-to-end tests cover text-only, mention, sticker-only, and text-plus-sticker policy outcomes.

---

## Phase 4 — Memory, Privacy, and Group Behavior

### Outcome

The assistant remembers useful group context without leaking private information.

### User Story 1

**As a group member,**
I want the assistant to remember useful group context,
so that conversations improve over time.

### User Story 2

**As a user,**
I want control over stored information,
so that I can protect my privacy.

### Scope

* Explicit memory records.
* Group memory.
* User preferences.
* Memory visibility policy.
* `/memory`.
* `/forget`.
* `/forget_me`.
* Memory expiration.
* Conversation summaries.
* Optional semantic memory.
* Memory audit tests.
* Ambient selective mode experiment.

### Acceptance Criteria

* Memories are scoped to a group, private conversation, or user.
* Private memories are excluded from group context by default.
* `/forget` removes the selected memory from future retrieval.
* `/forget_me` removes or anonymizes data according to the accepted retention policy.
* Deleted memory does not reappear through vector retrieval.
* Memory retrieval results include scope and source.
* Ambient mode can choose silence.
* Ambient mode is rate limited.
* No assistant-to-assistant response loop occurs.
* Privacy boundary tests pass.

---

## Phase 5 — Operational Scalability

### Outcome

The Telegram product can be operated reliably across multiple groups and application instances.

### User Story

**As an operator,**
I want the application to scale horizontally and expose failures,
so that I can operate it reliably.

### Scope

* Worker scaling.
* Queue visibility.
* Dead-letter handling.
* Central rate limiting.
* Provider concurrency limits.
* Provider fallback.
* Metrics and tracing.
* Alert-ready health signals.
* Load tests.
* Backup and restore runbook.
* Failure-recovery tests.
* Deployment configuration.

### Acceptance Criteria

* Multiple webhook instances can process updates without duplicate replies.
* Multiple workers preserve required conversation ordering.
* Retry does not duplicate an already completed Telegram action.
* Dead-letter work can be inspected and replayed safely.
* Provider concurrency is enforced across workers.
* Load tests meet accepted throughput and latency targets.
* Operator can identify a message flow through correlation IDs.
* Backup and restore procedure is documented and rehearsed.
* Deployment rollback procedure is documented.
* Failure simulations have observable evidence.

---

## Phase 6 — Administration Dashboard

### Outcome

An administrator can manage assistants, groups, personalities, stickers, and operational status through a web interface.

### Scope

* Authentication.
* Assistant management.
* Platform connection management.
* Group settings.
* Personality editor.
* Sticker registry.
* Usage dashboard.
* Error inspection.
* Memory administration.
* Audit history.

### Acceptance Criteria

* Unauthorized users cannot access administration.
* Changes are validated server-side.
* Personality changes are versioned.
* Secrets are not returned to the browser.
* Group settings changes are auditable.
* Dashboard state reflects backend source of truth.
* Critical operations require explicit confirmation.

---

## Phase 7 — Zalo Feasibility and Adapter

### Outcome

The team knows exactly which social-assistant behaviors are officially supported on Zalo and can implement the supported subset without changing core conversation logic.

### Scope

First stage:

* Create Zalo application and Official Account test environment.
* Validate token lifecycle.
* Validate webhook authentication.
* Validate one-to-one incoming and outgoing messages.
* Validate GMF capabilities.
* Validate mentions.
* Validate stickers and media.
* Document quotas and review requirements.
* Write an architecture decision.

Second stage, only after feasibility approval:

* Implement Zalo adapter.
* Normalize Zalo events.
* Execute supported outbound actions.
* Add Zalo-specific integration tests.
* Expose capability flags to response policy.

### Acceptance Criteria

* A written capability matrix distinguishes verified, unsupported, and unknown features.
* Each verified capability has observed sandbox evidence.
* Unsupported actions are blocked through capability policy.
* Conversation engine requires no Zalo-specific branch.
* Zalo identities are not automatically linked to Telegram identities.
* No unofficial personal-account automation is used.

---

# 19. Repository Layout for Codex and Harness

```text
project/
├── AGENTS.md
├── README.md
├── docs/
│   ├── README.md
│   ├── WORKFLOW.md
│   ├── HARNESS.md
│   ├── ARCHITECTURE.md
│   │
│   ├── product/
│   │   ├── SPEC.md
│   │   ├── BEHAVIOR.md
│   │   ├── SAFETY.md
│   │   ├── MEMORY.md
│   │   └── PLATFORM_CAPABILITIES.md
│   │
│   ├── decisions/
│   │   ├── ADR-001-modular-monolith.md
│   │   ├── ADR-002-platform-adapters.md
│   │   ├── ADR-003-structured-response-plan.md
│   │   └── ADR-004-memory-boundaries.md
│   │
│   ├── plans/
│   │   ├── active/
│   │   │   └── telegram-social-ai-mvp.md
│   │   └── completed/
│   │
│   ├── runbooks/
│   │   ├── local-development.md
│   │   ├── telegram-setup.md
│   │   ├── deployment.md
│   │   └── recovery.md
│   │
│   └── templates/
│
├── backend/
├── frontend/
├── tests/
├── scripts/
├── docker-compose.yml
└── .github/
    └── workflows/
```

---

# 20. Harness Rules for Codex

Codex must begin with `AGENTS.md`, then inspect only the relevant product, architecture, decision, plan, code, and validation surfaces.

The accepted authority order is:

```text
explicit product-owner decision
  -> current product contract
  -> architecture and ADRs
  -> active execution plan
  -> implementation and executable evidence
  -> completed historical plans
```

This follows the Harness source hierarchy.

## Bounded Task

For a small, bounded task, Codex should:

1. Restate the observable outcome.
2. Read relevant authority.
3. Inspect affected implementation and tests.
4. Make the smallest coherent change.
5. Run focused checks.
6. Run required repository checks.
7. Report changes, evidence, and remaining limitations.

No Harness database intake or trace operation is required.

## Durable Work

For multi-session work, Codex should:

1. Create or resume the active plan.
2. Keep progress current.
3. Record task-local decisions.
4. Promote lasting decisions into ADRs.
5. Implement in verifiable groups.
6. Record validation evidence.
7. Move the plan to `completed` only after verified completion.

## Human Decision Boundary

Codex must stop before mutation when:

* A new externally visible product policy has materially different choices.
* A change could weaken privacy or safety.
* Recovery is difficult.
* Validation would be removed or weakened.
* Platform behavior has not been officially verified.
* Credentials or permissions are insufficient.

Codex should not stop for minor implementation choices that do not alter accepted behavior.

---

# 21. Accepted Specification Sequence

The implemented and committed execution history is authoritative for completed
and active specifications. This sequence supersedes the earlier recommended
draft and must not renumber completed work.

```text
SPEC-001 Repository and Backend Bootstrap
SPEC-002 Database and Persistence Foundation
SPEC-003 Telegram Platform Adapter
SPEC-004 Telegram Ingress, Queueing, and Idempotency
SPEC-005 Conversation Domain and Context
SPEC-006 LLM Provider Abstraction and Response Planning
SPEC-007 Outbound Actions and Delivery
SPEC-008 Operator Bootstrap and End-to-End Demo
SPEC-009 Personality Profiles and Group Configuration
SPEC-010 Telegram Administration Commands and User Preferences
SPEC-011 Explicit Memory, Privacy, and Retention Controls
SPEC-012 Safety Policy and Rate Limiting
SPEC-013 Zalo Feasibility Spike and Platform Capability Matrix
SPEC-014 Zalo Operator Verification Gate
SPEC-015 Telegram MVP Observability and Operational Telemetry
SPEC-016 Telegram Operational Reliability, Recovery, and Scale Verification
SPEC-017 Telegram Ambient Selective Participation and Social Response Policy
SPEC-018 Telegram Conversation Summaries and Bounded Context Compression
SPEC-019 Explicit Memory Semantic Retrieval and Qdrant Derived Index
SPEC-020 Production Deployment, Secrets, and Runtime Operations
SPEC-021 Authenticated Operator and Group Administration Control Plane
SPEC-022 Telegram Production Integration and Live Acceptance
SPEC-023 Production Observability, SLOs, Alerting, and Incident Operations
SPEC-024 Safety Moderation, Abuse Prevention, and User Protection
SPEC-025 Data Governance, Encryption, Export, and Deletion Compliance
SPEC-026 Provider Routing, Cost Budgets, and Usage Governance
SPEC-027 User-Controlled Memory and Personal Context
SPEC-028 Rich Telegram Media and Voice Interactions
SPEC-029 Proactive Scheduling and Durable Social Participation
SPEC-030 Multi-Assistant / Multi-Tenant Product Model
SPEC-032 AI Evaluation and Conversation Quality Framework
SPEC-033 Telegram Knowledge Base / RAG
SPEC-034 Telegram Reply Context and Ordered Delivery
SPEC-035 Telegram Presence and Response Feedback
SPEC-036 Telegram Response Editing and Regeneration
SPEC-037 Telegram Reactions and Lightweight Social Feedback
SPEC-038 Explicit Telegram Voice Playback / TTS
SPEC-039 Explicit Conversation Feedback and Quality Signals
SPEC-040 Production Stabilization and Global CI Recovery
SPEC-041 Telegram-first Release Readiness and Production Acceptance
```

SPEC-014 is `DEFERRED / BLOCKED_ON_EXTERNAL_PREREQUISITE`: its Phase 1
preparation is complete, while credentialed verification waits for an
operator-owned dedicated nonproduction OA/application. This Zalo-only gate is
not on the Telegram MVP critical path. SPEC-015 and SPEC-016 are completed
Telegram observability and operational-reliability work. SPEC-019 is the latest
completed explicit-memory semantic-retrieval track. SPEC-020 is the Product
Owner-selected production deployment design and its repository implementation
is an approved candidate pending external deployment acceptance. SPEC-021 is
the completed authenticated operator control plane. SPEC-022 is approved and
committed; its live Telegram acceptance remains an externally gated
operational step. SPEC-023 is implemented as an approved candidate: the SLI
catalog, SLO targets with a rolling 28-day error budget, content-safe alert
rules, and incident operations are declared in code and documentation with no
schema migration; its proposed availability, delivery-confirmation, and
recovery-backlog objectives and notification channels remain operating-owner
approvals. SPEC-024 is implemented as an approved candidate: the safety
moderation, abuse prevention, and user protection contract in
`docs/product/specs/SPEC-024-safety-moderation-abuse-prevention-and-user-protection.md`
is enforced in the response-planning and outbound-delivery workers, exposed
through the `/safety`, `/protect`, and `/unprotect` commands and content-free
control-plane review endpoints, and backed by the additive `0015_safety_moderation`
migration and `safety_risk` alert rules; its threshold objectives remain
operating-owner approvals. SPEC-014 remains deferred
and no Zalo runtime is authorized. SPEC-025 is the Product Owner-approved
product contract for data governance, encryption, export, and deletion
compliance in
`docs/product/specs/SPEC-025-data-governance-encryption-export-and-deletion-compliance.md`;
its Product Owner-authorized candidate implementation is represented by the
uncommitted `0016_data_governance` worktree (ADR-0022) and is under final
validation, with pending operating-owner production approvals for deployment,
retention, encryption ownership, compliance declarations, and migration
execution. Migration `0016_data_governance` itself is Product Owner-authorized.
The final authorization adds an explicit tenant-independent
`deployment_operator` grant on the existing SPEC-021 identity boundary for the
content-free FR-04 deployment export; no tenant or group role implies that
authority, and the authority grants no tenant access.
SPEC-026 is the completed Product Owner-approved product contract for versioned provider
routing, content-safe usage accounting, operational cost estimates, and
pre-I/O deployment, Assistant, and PlatformConnection budgets in
`docs/product/specs/SPEC-026-provider-routing-cost-budgets-and-usage-governance.md`.
The Product Owner-authorized implementation is committed at `eec38fe`, including
migration `0017_provider_routing_cost_budgets`, governed runtime, control-plane,
telemetry, deployment, proof, and operations changes. Production prices, budget
amounts, health thresholds, ledger retention, and rollout remain operating-owner
decisions. Conversation and group budgets and expanded multi-tenancy remain out
of scope.

SPEC-027 is the Product Owner-approved contract for explicit user-controlled
memory and bounded personal context in
`docs/product/specs/SPEC-027-user-controlled-memory-and-personal-context.md`.
It authorizes deterministic inspect/create/correct/delete/clear/recall controls,
exact conversation-scoped participant ownership, private-conversation personal
context, immediate PostgreSQL authority, semantic-derived invalidation, and
SPEC-025/026 integration without cross-conversation identity or automatic
memory inference. SPEC-027 is committed at `7011154`; the post-merge migration
bootstrap/governance hotfix is committed at `8bc2353`.

SPEC-028 is the Product Owner-approved and implementation-authorized contract in
`docs/product/specs/SPEC-028-rich-telegram-media-and-voice-interactions.md`.
It covers bounded ephemeral Telegram photo/voice and supported audio processing,
derived transcript provenance, exact-scope privacy/export/erasure and enforced
provider governance. Repository candidate validation passed with Docker-backed
integration/migration/runtime verification pending; production activation remains
external. No automatic memory, permanent raw-media
archive, new provider vendor, TTS or video/document understanding is authorized.
SPEC-029 Proactive Scheduling and Durable Social Participation is the Product
Owner-approved and implementation-authorized contract in
`docs/product/specs/SPEC-029-proactive-scheduling-and-durable-social-participation.md`.
V1 is private-conversation only: bounded user-authored reminders and separately
consented code-owned check-ins use explicit IANA timezone, DST, quiet-hour,
catch-up, cancellation, privacy and durable-outbox semantics. It authorizes no
background provider generation, groups, workflow engine, inferred memory,
cross-conversation identity or SPEC-030 work. The repository candidate is under
final validation with Docker-backed PostgreSQL/Redis and runtime proof pending.
SPEC-030 Multi-Assistant / Multi-Tenant Product Model is the Product
Owner-approved contract in
`docs/product/specs/SPEC-030-multi-assistant-multi-tenant-product-model.md`.
It reuses the existing durable tenant and membership graph, gives every
Assistant exactly one immutable tenant and every PlatformConnection one
immutable tenant/Assistant owner, derives conversation authority through that
connection, and preserves exact conversation-local participant, memory,
schedule, media, export, and erasure scope. New Assistants/connections start
disabled and all external-I/O paths revalidate current lifecycle. It adds no
billing, self-service organization suite, cross-assistant identity/memory,
assistant orchestration, Zalo, or SPEC-031 behavior. The uncommitted repository
candidate is awaiting independent release audit.

Each SPEC should define:

* Outcome.
* User stories.
* In scope.
* Out of scope.
* Functional requirements.
* Acceptance criteria.
* Required tests.
* Dependencies.
* Risks.
* Rollback or recovery.
* Observable completion evidence.

---

# 22. Definition of Done

A task is complete only when:

* Requested behavior exists.
* Relevant product and architecture documents remain accurate.
* Tests appropriate to the behavior pass.
* Static validation passes.
* Integration behavior is observed when relevant.
* Migrations are tested when relevant.
* Secrets are not exposed.
* The active execution plan is updated when required.
* Remaining limitations are explicitly reported.

A phase is complete only when its acceptance criteria are verified through executable or observable evidence.

---

# 23. Open Product Decisions

The following decisions are still required to finalize version 1.0 of this SPEC.

## OQ-01 — Assistant Name (resolved)

**Owner decision, 2026-10-09:** the canonical project/product name is January.
The historical working name recorded in this document's metadata is retired
for current public identity; it is not an alias. Configured Assistant display
names remain separate resource metadata, not a new product naming decision.

---

## OQ-02 — Default Personality

Choose the closest default:

```text
A. Friendly and helpful
B. Gen Z and playful
C. Sarcastic but safe
D. Calm and intelligent
E. Custom description
```

Proposed default:

```text
B — Gen Z and playful, with low teasing
```

---

## OQ-03 — Group Message Visibility

Should the Telegram bot be allowed to receive ordinary group messages?

```text
A. Only mentions and replies
B. Read all messages but respond selectively
C. Administrator chooses per group
```

Proposed default:

```text
C, with A as the initial group default
```

---

## OQ-04 — Direct Messages

Should one-to-one Telegram conversations be included in MVP?

```text
A. Yes
B. No, group chat only
```

Proposed default:

```text
A
```

---

## OQ-05 — Initial LLM Provider

Which provider should be implemented first?

```text
A. OpenAI
B. Gemini
C. Groq
D. OpenRouter
E. Ollama
F. Multiple providers from the beginning
```

Proposed default:

```text
One hosted provider first, behind ModelProvider abstraction
```

---

## OQ-06 — Expected Launch Size

Provide estimates for:

```text
Number of groups:
Average group members:
Messages per group per day:
Maximum simultaneous active groups:
```

Proposed development assumption:

```text
50 groups
20 members per group
1,000 incoming messages per group per day
20 simultaneously active groups
```

---

## OQ-07 — Memory Retention

How long should ordinary messages be stored?

```text
A. 7 days
B. 30 days
C. 90 days
D. Until manually deleted
E. Store summaries but delete raw messages
```

Proposed default:

```text
30 days for raw messages; longer retention for explicit memories
```

---

## OQ-08 — Memory Creation

How should long-term memories be created?

```text
A. Only when a user explicitly says “remember”
B. Automatically for useful group facts
C. Both, with automatic memory visible to users
```

Proposed default:

```text
A for MVP; C in a later phase
```

---

## OQ-09 — Sticker Source

Which stickers should the assistant use?

```text
A. A custom sticker pack created for the assistant
B. Existing selected Telegram sticker packs
C. Both
```

Proposed default:

```text
A small curated custom pack
```

---

## OQ-10 — Humor and Teasing

Choose the initial limit:

```text
A. Friendly only
B. Light teasing
C. Moderate teasing with opt-out
D. Administrator-configurable
```

Proposed default:

```text
D, defaulting to B
```

---

## OQ-11 — Bot Administration

Who may change group configuration?

```text
A. Group creator only
B. Any Telegram group administrator
C. A configured list of Telegram user IDs
D. Both B and C
```

Proposed default:

```text
D
```

---

## OQ-12 — Product Language

Choose initial language behavior:

```text
A. Vietnamese only
B. Vietnamese and English
C. Automatically follow the user’s language
```

Proposed default:

```text
C, with Vietnamese as the default
```

---

## OQ-13 — Hosting

Where should the MVP run?

```text
A. Local server
B. VPS
C. AWS
D. Google Cloud
E. Azure
F. Another platform
```

This decision affects deployment, secret management, storage, observability, and cost controls.

---

## OQ-14 — Repository Language

Should repository documentation, code identifiers, and comments be:

```text
A. English
B. Vietnamese
C. English code and documentation, Vietnamese product examples
```

Proposed default:

```text
C
```

---

## OQ-15 — Zalo Timing

When should Zalo work begin?

```text
A. Only after Telegram MVP is stable
B. Telegram and Zalo adapters in parallel
C. Perform a Zalo feasibility spike early, then defer implementation
```

Proposed default:

```text
C
```

---

# 24. Recommended Immediate Decisions

Development can begin after confirming at least:

```text
OQ-03 — Group message visibility
OQ-05 — Initial LLM provider
OQ-06 — Expected launch size
OQ-10 — Humor and teasing
OQ-13 — Hosting
OQ-14 — Repository language
```

Other decisions can temporarily use the proposed defaults.

---

# 25. Recommended First Codex Outcome

The first Codex assignment should not build the Telegram bot immediately.

It should produce a repository that is ready for controlled development:

```text
Outcome:
Install and configure Repository Harness, establish product and architecture
authority, create the active Telegram MVP execution plan, bootstrap the backend,
and provide executable quality checks.

No Telegram webhook, LLM integration, memory, sticker, or Zalo implementation
is included in this first assignment.
```

Required first-task evidence:

* Repository structure.
* Accepted product SPEC.
* Architecture document.
* Active execution plan.
* Backend starts locally.
* Health endpoint responds.
* Unit test passes.
* Lint passes.
* Type checking passes.
* Docker configuration validates.
* CI workflow exists.

---

# 26. Current Telegram regeneration extension

The implemented product contract for response retry/edit UX is
[`SPEC-036-telegram-response-editing-regeneration.md`](specs/SPEC-036-telegram-response-editing-regeneration.md).
Users must reply to an authoritative assistant response with argument-free
`/regenerate`; no fuzzy or implicit regeneration exists. The retry answers the
original user turn using current eligible context and fresh provider governance,
is capped at three attempts per immutable root lineage, and treats Telegram
editing solely as a durable presentation option. Unsafe or split targets send a
new ordered response; ambiguous edits never trigger a duplicate fallback.

---

# 27. Current Telegram reaction extension

The approved lightweight social-feedback contract is
[`SPEC-037-telegram-reactions-lightweight-social-feedback.md`](specs/SPEC-037-telegram-reactions-lightweight-social-feedback.md).
Only addressed, ordinary, authoritative user text acknowledgements can map by
exact local rules to `👍` or `❤️`. The decision is provider-free and the
Telegram call is one non-durable attempt after terminal planning. It never
authorizes a response, becomes conversation context, or writes memory,
knowledge, summaries, media, or outbound actions. Commands, `/regenerate`,
ambient/proactive work, media, safety denial, foreign/disabled/redacted
authority, and reaction updates always produce none.

---

# 28. Current Telegram explicit voice extension

The approved voice-presentation contract is
[`SPEC-038-telegram-explicit-voice-tts.md`](specs/SPEC-038-telegram-explicit-voice-tts.md).
Users reply to one locally authoritative assistant text response with exactly
`/voice`. PostgreSQL resolves the whole logical source plan—including the exact
regenerated plan when applicable—and Telegram's quoted copy is ignored.

One enforced OpenAI `text_to_speech` route synthesizes the unchanged text using
`gpt-4o-mini-tts`, voice `alloy`, and native OGG/Opus. Source and output are
bounded at exactly 4,000 Unicode code points and 5 MiB. A short-lived,
same-scope PostgreSQL artifact survives definitive Telegram delivery retries;
provider or Telegram ambiguity never causes a blind repeat. Voice playback
creates no second semantic answer, chat-generation call, memory, knowledge,
summary, media/transcription, presence, reaction, or Zalo behavior.

---

# 29. Current production stabilization contract

The approved release-engineering contract is
[`SPEC-040-production-stabilization-global-ci-recovery.md`](specs/SPEC-040-production-stabilization-global-ci-recovery.md).
It introduces no user-facing behavior, production entity, setting, evaluation
scenario, or migration. The single schema head remains
`0026_conversation_feedback`.

Every Assistant continues to require an existing Tenant. Integration fixtures
must explicitly establish that authority and may not depend on a conditional
migration-created legacy row, earlier test order, or dirty local database.
`fk_assistants_tenant` remains validated and restrictive. Local stabilization
approval additionally requires every Quality command, repeated fresh-state
reliability, the unchanged 130 / 125 / 5 / 0 / 0 eval result, candidate script
modes, and a VCS-free clean-runner proof. Remote closure requires a later
reviewed commit/push and green GitHub Quality run.

---

# 30. Current Telegram-first release-readiness contract

The approved release-engineering contract is
[`SPEC-041-telegram-first-release-readiness-production-acceptance.md`](specs/SPEC-041-telegram-first-release-readiness-production-acceptance.md).
It adds no user-facing behavior or migration. It preserves single head
`0026_conversation_feedback` and starts from committed green baseline
`private-source-checkpoint-omitted`, GitHub Quality run
`36405527959`.

The contract distinguishes code/config readiness, actual production deployment,
and live external acceptance. Approval requires fail-closed production
configuration, migration preflight, coherent topology/readiness, synthetic
backup/restore, truthful rollback, complete Telegram/provider/privacy/
observability acceptance, all Quality validators, fresh services, VCS-free
proof, and zero Critical/High findings. Real credentials, DNS/TLS, production
data services, provider accounts, monitoring destinations, operating owners,
and promotion approval remain explicit external prerequisites.

### Current production promotion and live-acceptance contract

[`SPEC-042-production-promotion-live-acceptance.md`](specs/SPEC-042-production-promotion-live-acceptance.md)
uses approved source `private-source-checkpoint-omitted` and green
exact-SHA GitHub Quality `36721562006`. It distinguishes repository readiness,
promotion-package readiness, explicit authorization, actual deployment, fresh
live acceptance and observed post-deploy stability. No product behavior or
migration is added. Source head remains `0026_conversation_feedback`.

The release manifest (private execution record omitted from this snapshot) records immutable
local provenance and observed external availability. Deployment, publication,
production access/migration, DNS/webhook changes, real traffic, paid calls and
restore remain separately operator-gated. Synthetic proof never becomes live
PASS. The goal authorizes package preparation only when those approvals are absent.
