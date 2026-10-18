---
name: Bug or self-host support
about: Report a reproducible non-sensitive problem
title: ''
labels: ''
assignees: ''
---

Do not post vulnerabilities here; follow SECURITY.md first. Never attach .env,
Telegram tokens, provider keys, JWT/DB credentials, conversations, memory text,
real user/chat IDs, raw provider responses, private hostnames or database dumps.
Review and redact all output, including doctor and third-party errors.

## Source and deployment

- Commit SHA or tag (or archive identity):
- Profile (local development / local self-host / VPS polling / VPS webhook):
- Docker/Compose versions (Python/uv only for native development):
- Source Alembic head and running revision, if safely available:

## Reproduction

Minimal synthetic steps, expected behavior and actual behavior:

## Reviewed diagnostics

- Offline doctor phase and redacted result:
- Affected Compose service state and /live versus /ready result:
- Error class (not full logs or configuration):

See docs/runbooks/self-hosted-troubleshooting.md. Community support is
best-effort; no response time or live-account access is required.
