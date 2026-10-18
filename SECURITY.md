# Security reports

Do not publish bot tokens, provider keys, JWT/database secrets, full `.env` or
Compose dumps, private conversations, model prompts, raw provider responses,
database backups or exploitable vulnerability details in a public issue.

If this repository's GitHub Security page offers private vulnerability reporting,
use that private channel. Availability for the planned public repository remains unverified. This document does not claim a working
private channel or invent a reporting email address.

If no private channel is offered, request a private contact method without
including sensitive details or an exploit. Wait for the maintainer to confirm
the channel before sending those details. Maintainers should confirm private
reporting before publishing the self-host distribution candidate.

In a confirmed private channel, include the exact version/tag or source SHA,
affected deployment profile, prerequisites, expected versus actual behavior,
and minimal synthetic reproduction steps. Redact bot/provider tokens, JWT/DB
secrets, real user/chat IDs, private hostnames and user conversation/memory
content. Do not send a production dump or an exploit publicly while waiting
for contact. No bug bounty, supported-version LTS commitment or response SLA is
offered; security support is best-effort community maintenance.

For ordinary non-sensitive bugs, useful public evidence is the exact source SHA,
service state, redacted error class, expected/actual migration revision, safe
doctor output and `/live` versus `/ready` status. Review even bounded logs locally;
do not attach an automatic full support bundle.

Keep operator files private and outside Git/images. If a credential is exposed,
rotate/revoke it at its issuer, update protected local configuration and restart
affected services. Removing a token from a current file does not revoke it or
erase it from past Git history, logs or backups. Do not paste the old value into
a report. Retain privacy/erasure rules when handling backups and incident data.
