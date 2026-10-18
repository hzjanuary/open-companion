# Observability

SPEC-028 adds `january_telegram_media_operations_total` and
`january_telegram_media_operation_duration_seconds`. Labels are closed
kind/stage/outcome/reason enums only. Provider metrics additionally accept the
`transcription` workload and `media_transcription` operation. Missing usage is
unknown; cost metrics remain operational estimates. Never label or log media
bytes, transcripts, captions, file references, download paths or bot tokens.

SPEC-029 adds `january_schedule_commands_total`,
`january_schedule_occurrences_total`, `january_schedule_delivery_total`, and the
capped `january_schedule_backlog` gauge, plus the existing generic worker
counter/duration with runtime `scheduler` and operation `schedule_batch`.
The gauge reports pending/leased reminder/check-in rows up to one configured
batch plus one, so it signals saturation without an unbounded scan. Labels are
closed command/occurrence/delivery outcomes and reminder/check-in kind only.
Reminder text, timezone names, public or internal schedule IDs,
participant/conversation/Telegram IDs, command IDs, credentials, and arbitrary
errors are prohibited. Occurrence state—not a metric—is delivery truth.

SPEC-035 adds `january_telegram_presence_calls_total` and
`january_telegram_presence_lifecycle_total`. Their labels are closed success or
failure, platform-error category, and controller terminal outcome values only.
They never contain chat/thread/user/conversation/tenant/Assistant/connection/
job/provider-request identifiers, prompts, responses, or credentials. Presence
metrics are diagnostic evidence and never provider, planning, or delivery
authority.

SPEC-030 introduces no identifier dimensions. Multi-tenant routing,
authorization, and lifecycle outcomes use only existing closed reason/status
categories. Tenant IDs, Assistant IDs, connection/conversation/participant
IDs, tenant or Assistant names/slugs, and raw platform identifiers are never
metric labels. Approved opaque IDs may appear only in content-safe audit rows
under the existing audit policy.

Telemetry recording and export are independent. Both default to disabled.
When export is enabled it binds to `127.0.0.1:9464`; use a distinct local port
for each runtime process. Do not expose this endpoint beyond loopback without
an operator-owned network boundary.

```bash
JANUARY_METRICS_ENABLED=true \
JANUARY_METRICS_EXPORT_ENABLED=true \
JANUARY_METRICS_PORT=9464 \
uv run uvicorn app.main:app --app-dir backend
curl http://127.0.0.1:9464/metrics
```

The Prometheus-compatible text catalog uses `january_` names for HTTP,
ingress, eligibility, planning, provider, response-plan, outbound, safety,
rate-limit, and worker operation measurements. It never contains text,
prompts, memory, raw platform IDs, request/correlation IDs, usernames, URLs,
tokens, secrets, or exception bodies as labels or exposition values.

SPEC-018 adds content-free `january_summary_jobs_total`,
`january_summary_generation_total`, `january_summary_context_usage_total`, and
`january_summary_retention_events_total`. Their labels are only closed outcomes,
provider, and schema version; summary text, source text, IDs, and source hashes
are never telemetry values.

SPEC-019 adds content-free semantic query/index/fallback and embedding metrics.
Their labels are closed operation/outcome/provider/version categories only;
memory IDs, conversations, query text, memory text, vectors, Qdrant bodies, and
provider bodies are never labels or log fields.

SPEC-016 adds `january_recovery_events_total`,
`january_dead_letter_events_total`, `january_quarantine_events_total`, and
`january_provider_concurrency_events_total`. Their only labels are closed work
kind, operation/outcome/reason, or provider. They are alert-ready evidence for
retry exhaustion, quarantine accumulation, and capacity saturation, not a
production SLO claim.

SPEC-025 adds content-free governance metrics:
`january_governance_export_requests_total`,
`january_governance_packages_cleared_total`,
`january_governance_export_retrievals_total`,
`january_governance_erasure_requests_total`, and
`january_governance_audit_retention_total`. Their labels are closed scope and
outcome values only; tokens, hashes, export package bodies, audit detail,
conversations, and participants are never telemetry values.

SPEC-027 adds `january_memory_control_operations_total`. Its only dimensions
are closed operation, outcome, record-kind, and private/group classes. Memory
or personal-context content, record/participant/conversation/Telegram IDs,
command arguments, prompts, and derived-index identifiers are prohibited.

`request_id` identifies one HTTP request. A correlation ID is a separate opaque
durable-work root and is logged, never used as a metric label. JSON logs are
allowlisted operational events and omit product content and credentials.

Provider usage is counted only when the provider reports it. Configure optional
prices as JSON with integer `input_microusd_per_million` and
`output_microusd_per_million` rates keyed by `provider:model`. Estimates are
not invoices; absent rate or usage is unknown. CI does not claim production
latency/SLO compliance; component-duration histograms provide the evidence for
operators to measure it in their own environment.

Run `./scripts/validate-observability.sh` for no-network telemetry proof.
