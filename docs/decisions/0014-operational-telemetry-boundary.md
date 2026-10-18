# ADR 0014: Operational Telemetry Boundary

## Decision

Use an application-level `MetricsRecorder` port with an explicitly owned
per-runtime registry. Infrastructure provides an in-memory Prometheus-text
registry and a loopback-only local exporter; application code receives no
Prometheus SDK object.

## Consequences

Counters and histograms are process-local and external collectors aggregate
replicas. Export is disabled by default and never changes readiness semantics.
Metrics use only closed labels and do not persist in PostgreSQL. Telemetry
failure is contained so it cannot cause duplicate provider or Telegram I/O.
