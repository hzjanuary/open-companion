# SPEC-015: Telegram MVP Observability and Operational Telemetry

## Outcome

Add platform-neutral, content-safe operational telemetry to the active Telegram
MVP without changing conversation, safety, delivery, privacy, or rate-limit
policy. SPEC-014 remains deferred and no Zalo runtime is introduced.

## Contract

Each runtime owns an isolated metrics registry. The current exporter uses
Prometheus-compatible text exposition, is disabled by default, and binds only
to loopback when explicitly enabled. Metrics have closed low-cardinality labels
only; request, correlation, conversation, participant, message, Telegram, and
provider IDs never become labels.

Operational JSON logs may carry opaque internal IDs and correlation IDs but
never message, memory, prompt, generated text, raw Telegram data, credentials,
or arbitrary exception/provider bodies. Request IDs remain HTTP-local;
correlation IDs identify durable asynchronous work where available.

Provider counters/durations are recorded only for real provider invocations.
Reported usage is observed as complete, partial, missing, or invalid. Estimated
cost is optional, uses only `JANUARY_METRICS_PROVIDER_PRICING` integer
micro-USD-per-million-token rates, and is an operational approximation rather
than billing truth. Missing usage or price is unknown, never zero-cost.

## Metrics And SLO Evidence

The `january_` catalog covers HTTP, Telegram ingress, eligibility, planning,
provider requests/latency/usage/cost, response-plan validation, outbound and
delivery, safety, rate limits, and worker operations. Histograms measure
component boundaries: webhook acknowledgement, health request, provider I/O,
conversation worker, and delivery. Cross-process mention/command completion is
not asserted without a persisted end-to-end timestamp; production SLO
compliance is not claimed by CI or synthetic validation.

## Validation

```bash
./scripts/validate-observability.sh
```

The validator uses synthetic data, no credentials, no public network, and no
migration. It proves registry isolation, safe exposition, log/correlation
boundaries, exporter loopback behavior, and provider usage/cost semantics.
