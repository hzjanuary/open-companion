# SPEC-011: Explicit Memory, Privacy, and Retention

January creates long-term memory only from `/memory remember <fact>`. It is
untrusted user data and has same-conversation visibility only: no automatic
extraction, semantic retrieval, embedding, summary, or cross-conversation use.

The supported grammar is `/memory`, `/memory list`, `/memory remember <fact>`,
`/memory reset_group confirm`, `/forget <public-id>`, `/forget_me`, and
`/forget_me confirm`. Facts normalize whitespace, reject control characters,
and are limited to 500 characters. Creation is idempotent per command job.

Creators may delete their memory. Group deletion of another creator's memory
and group reset require fresh Telegram owner/administrator authorization;
private chats do not call that API. Commands are deterministic and never invoke
a model provider.

Deleted/expired memory clears content and its hash immediately. Technical rows
and content-free events retain only IDs, codes, reasons, counts, and timestamps
for idempotency and referential integrity. `/forget_me confirm` erases or
anonymizes the current Assistant/Telegram connection's relevant profile and
authored content while retaining only technical tombstones required for
idempotency, opt-out recognition, referential integrity, and abuse controls.
It cannot retract delivered Telegram messages, provider requests already in
flight/completed, provider copies, or backups.

Raw incoming payloads, message text/metadata, response-plan text, terminal
outbound payloads, and completed command arguments are cleared after at most
30 days. Pending work is not redacted. Explicit memory does not expire merely
because source-message content expires. Retention runs in a bounded no-network
PostgreSQL worker. At most ten active scoped memories may enter model context
under a separate 1,200-character budget as JSON-delimited untrusted data.

Migration `0008_memory_privacy_retention` adds the schema and supports clean
downgrade to `0007_telegram_commands`. This is not a claim of legal-compliance
certification, Telegram/provider/backup deletion, data export, or a public
privacy dashboard.
