# Ambient Participation

Ambient group participation is disabled by default. Enable it only after the
normal validation set and `./scripts/validate-ambient.sh` pass:

```bash
JANUARY_AMBIENT_SELECTIVE_ENABLED=true
```

Group administrators can use `/mode ambient_selective` and `/frequency low`,
`/frequency normal`, or `/frequency high`; `/frequency status` and `/status`
report the immutable current revision. These commands require the existing
fresh Telegram administrator authorization and never invoke a model.

To roll back, set `JANUARY_AMBIENT_SELECTIVE_ENABLED=false` and restart
workers. Existing group configuration is retained, ordinary ambient candidates
stop before provider I/O, and addressed mentions/replies continue normally.
Telemetry contains only bounded outcome, profile, and policy labels.
