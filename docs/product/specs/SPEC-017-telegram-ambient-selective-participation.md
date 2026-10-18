# SPEC-017 Telegram Ambient Selective Participation

Ambient participation is an opt-in group behavior. The deployment gate
`JANUARY_AMBIENT_SELECTIVE_ENABLED=false` is the default and turns persisted
ambient groups into addressed-only behavior without changing their revisions.

Addressed messages (private messages, mentions, replies, and supported name
matches) bypass ambient sampling and cooldown. Ordinary supported group text in
an `ambient_selective` revision is an ambient candidate. Immutable revisions
store `low`, `normal`, or `high` frequency; `ambient-policy-v1` defines their
sampling, cooldown, and confidence defaults.

Sampling is SHA-256 over internal message ID, configuration revision ID, and
policy version. Confirmed outbound actions with `ambient` origin are the sole
cooldown source. Silence, rejected delivery, and ambiguous delivery do not
start it. Ambient plans cannot tease or mention members, and low-confidence or
suppressed plans create no outbound action.
