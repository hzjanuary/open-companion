# SPEC-035 — Telegram Presence and Response Feedback

Status: **APPROVED PRODUCT SPEC**. The Product Owner's SPEC-035 request is the
authority for this bounded Telegram-first work. Global Quality CI remediation
is explicitly deferred and is not part of this specification.

## Purpose

Show Telegram's native `typing` chat action while an eligible, directly invoked
response is undergoing provider-backed generation. The signal must be timely,
bounded, content-free, best effort, and subordinate to all existing authority,
safety, governance, cancellation, lease, and response-delivery behavior.

## Existing-system audit

The response-planning worker already separates deterministic and ambient exits
from provider generation, revalidates tenant/Assistant/connection authority,
applies safety and rate controls, and routes provider calls through durable
governance. The governed provider enters its external-I/O state only after
budget, provider-rate, concurrency, and authority checks. The Telegram adapter
already owns one reusable HTTP client and one token-safe `_request` path.

Missing behavior is a typed `sendChatAction` boundary, precise eligibility,
admission-aligned start, an owned bounded refresh lifecycle, per-refresh lease
fencing, best-effort failure classification, and content-free proof.

## Eligibility and exclusions

V1 presence is eligible only when all of the following are true:

- the canonical platform is Telegram;
- the planning trigger is `addressed`, covering private direct messages,
  explicit group mentions, direct replies, and supported directly addressed
  media turns;
- current tenant, Assistant, platform connection, conversation, privacy, and
  planning-job authority permits the work;
- pre-generation safety permits generation;
- the selected provider attempt has passed every applicable routing, budget,
  rate, and concurrency admission check; and
- provider I/O is actually about to begin.

Presence is never emitted for ambient participation, proactive schedules,
deterministic commands or preferences, invalid or disabled authority, rejected
safety or provider admission, terminal or recovered jobs, unsupported
platforms, or work that completes without provider generation. Zalo remains
frozen.

## Start boundary

For governed providers, start presence after the durable provider attempt is
admitted and marked `io_started`, immediately before raw provider I/O. For
legacy mode, start at the end of its existing successful pre-provider gate,
immediately before the provider call. Starting is idempotent across transport
retry, correction, or fallback attempts in the same planning execution.

The initial Telegram request occurs with no database session, transaction,
lock, or checked-out connection held. A presence failure never changes routing,
budget reservation, token limits, retry policy, response content, planning
outcome, or outbound delivery.

## Telegram contract

Add one typed request carrying canonical Telegram chat ID and optional message
thread ID. The adapter calls `sendChatAction` with the closed action `typing`
through its existing `_request` method and reusable client. Chat IDs are opaque,
non-empty strings. Thread IDs use the adapter's existing positive-decimal
validation. A successful Telegram envelope must contain boolean `true`.

No placeholder message, editable draft, reaction, sticker, custom action,
streaming output, or presence persistence is introduced.

## Refresh policy

The constants are code-owned and deliberately not user configuration:

- initial send: immediately at admitted provider-I/O start;
- refresh interval: 4 seconds;
- maximum lifetime: 20 seconds from start; and
- maximum calls: 5 total, including the initial send.

Telegram chat actions are short-lived, so a four-second refresh avoids visible
gaps without request churn. Five total calls bound one planning execution and
place refreshes at approximately 4, 8, 12, and 16 seconds; the 20-second ceiling
prevents a late boundary call and limits stale feedback during a slow provider.
Provider work may continue after presence expires.

## Ownership, cancellation, and fencing

One execution-scoped controller owns at most one refresh task. It performs the
initial send synchronously and owns, cancels, and awaits every refresh path.
Stop is idempotent and is awaited before the planning execution completes,
returns, retries externally, or propagates cancellation/error. No detached or
orphan task is allowed.

Before each refresh, a cheap database query must verify the exact planning job,
lease owner, claim attempt, unexpired lease, non-terminal status, and active
tenant/Assistant/connection/conversation authority. The query scope closes
before Telegram I/O. Loss of any fence disables presence immediately. The stop
boundary serializes with sends so no new chat-action request begins after stop
has completed.

## Failure behavior

`sendChatAction` is best effort. Expected adapter failures—HTTP 400, 401/403,
429, 5xx, timeout, connection/network failure, and malformed response—are
classified through the existing typed adapter error. The first presence failure
disables further presence calls for that execution and records content-free
evidence. It is not retried by the controller and never blocks or mutates the
main response pipeline. Programmer defects and process cancellation remain
visible rather than being broadly swallowed.

## Persistence, privacy, memory, and knowledge

Presence adds no table, column, durable retry, recovery item, outbox action,
message, response plan, memory, semantic-memory, knowledge, summary, or media
row. Alembic head remains `0023_telegram_reply_ordered_delivery`; no `0024`
migration is authorized.

Metrics and logs use only closed operation/outcome/reason values. They must not
contain message content, response content, chat, thread, user, participant,
conversation, tenant, Assistant, connection, planning-job, provider-request, or
credential identifiers.

## Observability

Record bounded content-free counters for presence calls and controller terminal
outcomes. Allowed call outcomes are `success` and `failure`; failure reasons are
the closed platform error categories. Controller outcomes distinguish ordinary
stop, maximum lifetime/call exhaustion, authority-or-lease loss, and initial
failure. Identifier-bearing labels and content-bearing logs are forbidden.

## Evaluation and acceptance

SPEC-032 gains hard deterministic scenarios covering eligible direct presence,
direct media presence, ambient/proactive/command exclusion, safety and provider
admission denial, failure isolation, refresh bound, and cancellation/lease loss.
They run offline without Telegram, provider, database, or other credentials and
introduce no soft `NOT_EVALUATED` result.

Acceptance requires the complete proof matrix named by the Product Owner,
including exact adapter payload, zero-call exclusions, admission ordering,
database-session fencing, heartbeat limits, all failure classes, cancellation
and race behavior, no task leaks, zero durable content side effects, unchanged
migration head, executable clean-candidate validation, and visible global debt.

## Deferred global CI debt

At baseline, `validate-reliability.sh` fails six historical
`test_memory_schema.py` cases with `fk_assistants_tenant` because tenant
`00000000-0000-4000-8000-000000000030` is absent. This is **KNOWN PRE-EXISTING
CI DEBT — DEFERRED BY PRODUCT OWNER**. SPEC-035 must neither repair nor suppress
it. Any different failure is a SPEC-035 regression and blocks candidate
approval.
