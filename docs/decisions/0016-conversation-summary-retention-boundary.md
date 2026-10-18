# 0016 Conversation Summary Retention Boundary

Status: Accepted

## Decision

Conversation summaries are short-lived, same-conversation and same-thread
derived context, not explicit or semantic memory. A summary is created only
from retained, non-redacted incoming raw messages. Summary text is never an
input to a later summary.

`expires_at` is the earliest `source_message.platform_sent_at +
raw_content_retention_days` deadline in its source window. Privacy erasure
invalidates all completed summaries in affected conversations and clears their
text. Retention clears expired summary text. Planning may use at most one valid
summary before non-overlapping recent raw context.

## Consequences

Feature disable immediately restores raw-history-only planning without deleting
stored summaries. Summary generation runs in an optional worker and never adds
provider I/O to Telegram ingress, conversation processing, or response planning.
