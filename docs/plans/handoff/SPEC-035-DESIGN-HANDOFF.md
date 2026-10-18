# SPEC-035 Design Handoff

Date: 2026-09-19

Status: **APPROVED DESIGN**. Product authority is
`docs/product/specs/SPEC-035-telegram-presence-response-feedback.md`.

## Architecture

Add `SendChatActionRequest` and `SEND_CHAT_ACTION` to the existing platform port.
`TelegramAdapter.send_chat_action()` accepts only the closed `typing` action,
validates the existing chat/thread identifiers, and uses the adapter's reusable
client and `_request` envelope/error path. The response-planning worker accepts
an injectable platform adapter and otherwise creates one lazily from existing
Telegram settings. It closes only adapters it owns.

An application-level `TypingPresenceController` owns the bounded lifecycle. It
has injected send, fence, monotonic clock, sleep, and metrics dependencies so
unit tests can drive every transition with events and a controlled clock. The
controller sends once during `start`, then owns at most one refresh task. A
send lock and stopped flag serialize refreshes with idempotent `stop`; stop
cancels and awaits the owned task on every terminal or exceptional worker path.

## Timing policy

Use code-owned constants: immediate initial call, 4-second refresh interval,
20-second maximum lifetime, and 5 total calls. These produce at most four
refreshes before the lifetime boundary, matching Telegram's short chat-action
display while imposing a strict request and stale-feedback ceiling. They are
not settings or control-plane policy.

## Admission integration

The controller is constructed only for Telegram `addressed` planning work after
context, media preparation, privacy, safety, and planning-rate gates pass.

For governed mode, extend the provider decorator with an optional
`on_io_start` callback. Invoke it only after reservation, provider-rate,
concurrency, authority, and durable `mark_io_started` succeed, directly before
the raw provider call. For legacy mode, invoke the same idempotent controller
start at the successful end of `before_provider`, after its provider-rate gate.
Budget/routing/admission behavior is otherwise byte-for-byte unchanged.

Provider fallback, retry, and correction reuse the one controller. A denied
attempt cannot start it; a later admitted fallback may. Presence is stopped in
the generation `finally`, before the worker completes or propagates any result,
error, or cancellation.

## Lease and lifecycle fence

Add a planning-repository read that accepts exact job ID, lease owner, and
claim-attempt ordinal. In one short session it requires planning status leased,
matching owner/attempt, lease expiry in the future, active conversation, and
active canonical tenant/Assistant/platform connection authority. It returns a
boolean and closes the session before the controller invokes Telegram. This is
used before every refresh; the already established provider admission boundary
is the initial-call fence.

## Failure isolation

The controller catches only `PlatformAdapterError` from presence calls. On the
first such failure it emits a closed metric, disables itself, and stops future
refreshes. It does not sleep-retry, modify provider or response state, or hide
unrelated defects. `CancelledError` propagates while structured cleanup still
cancels and awaits the refresh task.

## Persistence and side effects

No schema, migration, durable retry, outbound action, or recovery object is
added. Presence calls are transient. Tests take table-count deltas for message,
response-plan, outbound, memory, semantic-memory, knowledge, summary, and media
surfaces. Alembic head stays `0023_telegram_reply_ordered_delivery`.

## Telemetry

Add low-cardinality counters to the existing catalog for call outcome/failure
category and controller stop reason. No identifier, content, or credential is a
label or log value. Metrics are evidence only and never control execution.

## Validation strategy

Unit adapter tests prove the exact payload, thread validation, boolean envelope,
and 400/401/403/429/5xx/timeout/reset/malformed classification. Controlled
controller tests prove immediate start, refresh schedule, caps, first-failure
disablement, idempotent stop, cancellation, send/stop race, lease loss, and zero
remaining tasks without real multi-second sleeps.

Live PostgreSQL planning tests prove direct addressed eligibility; zero calls
for ambient, inactive, expired, recovered, and terminal work; governed ordering;
exact lease fencing; zero checked-out connections during Telegram I/O; ordinary
response completion after every typed presence failure class; and zero durable
content side effects. Unit admission tests prove provider denials emit no call,
while SPEC-032 hard offline scenarios prove reply/media eligibility and
proactive/deterministic/safety-denied exclusions. A strict executable validator
proves the focused suite in the workspace and a clean tracked-plus-untracked
export without credentials, history, ignored dependencies, or hidden state.

## Known global CI debt

The exact six historical `test_memory_schema.py` failures with
`fk_assistants_tenant` for missing tenant
`00000000-0000-4000-8000-000000000030` remain deferred. The reliability
validator stays strict; SPEC-035 records the diagnostic and may not suppress or
repair it.
