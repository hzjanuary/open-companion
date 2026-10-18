# Encryption Ownership

This is the single authoritative encryption-ownership model for January
(SPEC-025, FR-10). For each surface it states who provides the control (the
product or the operating owner), what the product guarantees, and what the
product intentionally does not provide.

| Surface | Owner | Product guarantee | Not provided |
| --- | --- | --- | --- |
| In transit | Operating owner provides TLS/HTTPS; product requires it | Webhook requires HTTPS; secrets never sent in cleartext by the product | — |
| At rest — database and volumes | Operating owner (storage/volume encryption) | Product persists no plaintext secrets at rest | Application-level field encryption |
| At rest — secrets | Product | Secrets injected at the process boundary, never persisted in the database, logs, or audit, never logged | — |
| Derived index (Qdrant) | Product | Privacy-sensitive vectors plus opaque internal scope identifiers; rebuildable from authorized explicit facts | Memory text and personal-context records are never stored in the index |
| Personal context and recall | Product schema; operating-owner storage encryption | Creator-private exact-conversation scope, physical content clearing, content-free recall authority | Application-level field encryption or cross-conversation identity |
| Backups | Operating owner | Backup procedure mandates encryption | — |
| Key management | Operating owner | Rotation procedure exists (SPEC-020); keys never logged | — |
| Logs, metrics, audit | Product | Content-safe by construction | — |
| Provider governance ledger | Product schema; operating-owner storage encryption | Content-free policy, usage-quality, estimate, and reservation metadata; credentials and provider content are excluded | Billing truth or application-level field encryption |

Baseline commitments (SPEC-020) remain: secrets are injected at the process
boundary, never persisted in the database or logs, never logged, and rotated
through the documented procedure.

Application-level field encryption is explicitly future work, not a current
guarantee.
