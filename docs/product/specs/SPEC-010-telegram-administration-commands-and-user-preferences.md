# SPEC-010 Telegram Administration Commands and User Preferences

January accepts deterministic Telegram text commands only from a zero-offset
`bot_command` entity using Telegram UTF-16 entity offsets. Commands are
normalized before application logic; slash prose, captions, edits, and commands
addressed to another bot do not create command work.

Supported commands are `/start`, `/help`, `/status`, `/mode`, `/quiet`,
`/resume`, `/personality`, `/stickers`, `/mentions`, and `/teasing`. Grammar is
bounded and code-owned. Unknown or malformed addressed commands receive a short
deterministic help or usage reply. Command execution never invokes an LLM.

Each recognized command is persisted with the conversation ledger and creates
one leased command job. Completion atomically creates a response plan and uses
the normal outbound-action compiler; the response-plan source is exactly one
of a model planning job or a command job. Replays and expired leases cannot
produce a second command response plan.

Group configuration mutations require fresh current owner/administrator
authorization through the platform-independent `get_chat_member` contract.
Authorization occurs outside database transactions; private conversations do
not make that provider call. Mention and teasing commands change only the
requesting participant and write a preference event when state changes.

Telegram command-menu registration is deliberately deferred. Menu visibility
is not authorization and command handling is complete without it.

## Non-goals

This specification adds no public administration API, command framework,
Telegram SDK, LLM/provider execution, prompt editing, cross-user preferences,
or SPEC-011 behavior. Command responses are compact Vietnamese by default and
English for English personalities; they expose no credentials, raw IDs, prompt
text, or operational details.

## Acceptance

Validation uses fake authorization and delivery only. It proves entity-aware
parsing, bounded grammar, durable job leasing, safe authorization outcomes,
preference changes, response-plan XOR, and normal outbound delivery. The
remaining semantic limitation is that the current response-plan schema has no
formal teasing target; opted-out participants are removed from explicit mention
actions and represented in model context, but full semantic teasing
classification remains future work.
