# Encryption Ownership

This is the single authoritative encryption-ownership model for January
(SPEC-025, FR-10). For each surface it states who provides the control (the
product or the operating owner), what the product guarantees, and what the
product intentionally does not provide.

| Surface | Owner | Product guarantee | Not provided |
| --- | --- | --- | --- |
| In transit | Operating owner provides TLS/HTTPS and network access restrictions | Public webhook URL requires HTTPS; production configuration requires HTTPS for Telegram and enabled hosted providers | Automatic TLS termination or encryption of every local/internal connection |
| At rest — database and volumes | Operating owner (storage/volume encryption) | Credentials are not application database fields; conversation and memory content is stored without field encryption | Application-level field encryption |
| At rest — secrets | Operating owner protects private configuration files; product consumes injected secrets | Secrets are not persisted in application database, logs or audit | Encryption of operator env files or automatic key management |
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

Self-hosted operator env files contain plaintext credentials and require private
permissions and owner-managed storage/backup encryption. January does not encrypt
these files. The owner provides certificates, TLS termination, storage and volume
encryption, encrypted backups, key management, restricted network/admin access
and backup retention. Local HTTP services and local Ollama are not automatically
TLS-protected. Telegram remains external with any model choice. January provides
neither application-level field encryption nor end-to-end encryption.
