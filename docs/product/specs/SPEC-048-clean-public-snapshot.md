# SPEC-048 — January v0.1.0 clean public source snapshot

Date: 2026-10-17

Status: LOCAL STAGING — INDEPENDENT AUDIT REQUIRED

The owner approves v0.1.0 and the planned public repository
https://github.com/hzjanuary/open-companion. The release is NOT YET PUBLISHED;
no tag, root commit, remote, push or visibility change is created in this phase.
The private original remains immutable and its history is never imported.

Review every proposed public file for credentials, private records, personal
email/checkout paths, private infrastructure and development provenance. Report
redacted categories and locations only. Stop on actual credentials/private
records, uncertain legal attribution, unrecoverable privacy, source Git
contamination, unavailable validation prerequisites or production runtime defects.
Do not weaken tests or skip required proof to accommodate filtering.

Preserve MIT/NOTICE verbatim, required source/migrations/tests, current contracts,
architecture, technical designs, self-host operations and contributor guidance.
Classify files individually; exclude private execution and owner publication
receipts. Repair documentation links and preserve recorded executable modes.
Package metadata and draft CHANGELOG/notes use 0.1.0 without a fabricated date.

Run all canonical Quality blocks serially and applicable supplementary checks
with owned PostgreSQL 16, Redis 7 and Qdrant v1.13.4 plus fake external adapters.
Runtime behavior, architecture, pool defaults and migrations remain unchanged;
sole Alembic head stays 0026_conversation_feedback. Validate a clean VCS-free
materialization; full history coverage must fail closed with exit 2 while
synthetic scanner tests pass outside the final snapshot.

Bind final classifications, redacted dispositions, changes, exclusions, source
manifest/hashes and exact validation exits in separate owner-only private evidence.
Independent OpenCode audit must inspect that evidence and the exact snapshot.
Future publication requires a separately authorized NEW root commit using the
owner's exact GitHub Settings noreply address for both author and committer,
exact-SHA public remote CI, a verified private disclosure channel, settings and
visibility approval, then separately authorized tag/Release actions.

See [plan](../../plans/completed/SPEC-048-clean-public-snapshot.md),
[publication procedure](../../maintainers/first-public-publication.md) and
[draft notes](../../releases/first-public-release-candidate.md).
