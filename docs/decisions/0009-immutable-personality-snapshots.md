# ADR 0009: Immutable Personality and Configuration Snapshots

Personality profiles are stable logical records with append-only typed versions.
Conversation configuration is append-only revisions. A planning job stores the
selected version and revision IDs in its creation transaction, so a later group
change cannot alter in-flight or historical generation semantics.

The effective personality is a pure merge of the immutable base and allowed
nullable overrides. Hard safety fields are not overridable. Operator mutation is
an explicit runtime surface; Telegram administration commands are deferred to
SPEC-010.

The snapshot establishes generation semantics, but it does not override later
safety changes. Workers check current pause state before provider I/O and
current sticker enablement before Telegram I/O. Work already handed to an
external provider or platform can complete; the system makes no exactly-once or
instant-cancellation claim for that boundary.
