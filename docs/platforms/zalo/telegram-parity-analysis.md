# Telegram Parity Analysis

The comparison is evidence-based, not an adapter design. `exact` means official
evidence supports the current behavior; `partial` means a narrower OA behavior
is documented; `unknown` is not a promise; `none` is a documented or practical
surface mismatch.

| January Telegram baseline | OA direct interaction | OA GMF | Ordinary Zalo friend group | Notes |
| --- | --- | --- | --- | --- |
| DM inbound/outbound text | partial | unknown | unknown | OA messaging is documented but policy-gated. |
| Private group participation | none | unknown | unknown | GMF is a distinct OA product, not ordinary group parity. |
| Webhook inbound | partial | unknown | unknown | OA user-message webhook exists; payload/retry details need verification. |
| Polling fallback | unknown | unknown | unknown | No official polling evidence found. |
| Update dedupe/order | unknown | unknown | unknown | Retain durable at-least-once design. |
| Reply, mentions, stickers | unknown | unknown | unknown | Do not reuse Telegram entities or assets. |
| Admin role/member lookup | none | unknown | unknown | GMF role APIs need verification. |
| Command entities/topics | none | unknown | unknown | Telegram-specific input assumptions. |
| Outbound confirmation | unknown | unknown | unknown | Keep terminal ambiguity policy. |
| Privacy/local deletion | partial | unknown | unknown | Local deletion is reusable; OA UID is scoped to an OA. |
| Safety/rate limiting | exact | exact | exact | January policies are platform-neutral; external policy budgets differ. |

Surfaces must remain distinct:

- **Ordinary personal/group chat:** no supported public-API parity was verified.
- **OA direct interaction:** a narrower policy-constrained business assistant is plausible.
- **OA GMF:** an OA-specific group surface whose operational semantics require
  a dedicated test-OA verification.
- **ZBS template messaging:** policy/template messaging, not conversational
  group parity.
- **Social API/login and Social Plugins:** separate products; neither proves
  OA/GMF messaging capability.
