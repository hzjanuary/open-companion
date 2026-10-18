# SPEC-018 Telegram Conversation Summaries And Bounded Context Compression

SPEC-018 adds optional, short-lived conversation-scoped derived context for
long Telegram conversations. It is not explicit memory, semantic memory, a
profile, cross-conversation state, or a user-facing recap.

Summaries use retained non-redacted incoming raw messages only. The optional
worker creates them outside response handling, applies existing provider
rate/concurrency gates, and stores strict `conversation-summary-v1` output.
Planning uses at most one valid same-thread summary with raw current/reply
context and non-overlapping recent history. Disabled, missing, invalidated, or
expired summaries fall back to raw history.

Summary expiry is the earliest retention deadline of all source messages;
summary text is never re-summarized. `/forget_me` invalidates affected
conversation summaries before they can be read, and the retention worker clears
expired derived content. Synthetic validators prove structural and privacy
invariants only; they make no factual-quality claim.
