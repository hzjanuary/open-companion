# Harness Status

Harness core version `0.1.7` is installed at this repository and is current as
of 2026-07-29. `scripts/bin/harness status` and `scripts/bin/harness doctor`
pass without missing or modified managed files.

Harness provides repository navigation and durable plans. The default workflow
is repository-centered: product documents, accepted decisions, code, tests,
runtime behavior, and validation output are authoritative. The optional SQLite
compatibility control plane is not configured or required for January.

Use `scripts/bin/harness status` to inspect the installation and
`scripts/bin/harness doctor` to validate it. Do not reinstall or overwrite the
core unless those commands identify a concrete problem.
