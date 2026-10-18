# Release notes template

Copy for an actual owner-approved release; placeholders below are not a release.
Never include environment values, credentials, raw logs or user content.

## Identity

- Owner-approved version/tag:
- Release date (actual publication date):
- Exact source SHA and source archive:
- GitHub Quality run URL, exact head SHA, branch/event and completed result:
- Alembic head:
- Optional locally built image ID / published image digest (state which):
- Target platform and dependency/base-image provenance, when building images:

## Changes

Summarize applicable Added, Changed, Fixed and Security items from
[CHANGELOG](../../CHANGELOG.md), not every historical SPEC. Explain breaking
changes and configuration names/default changes without secret values.

## Migration and self-host upgrades

State NONE when no migration. Otherwise list the reviewed source/target revision,
one-owner migration steps and recovery limitations. Link
[self-hosted upgrades](../runbooks/self-hosted-upgrades.md): backup and erasure
record, review config, preflight, upgrade, readiness/worker checks and deliberate
smoke. Never imply arbitrary downgrade or real-data restore was tested.

## Validation and limitations

Record full Quality and independent audit, exact source archive/modes,
fresh/shallow/VCS-free proof, tested runtime versions and known limitations.
Distinguish synthetic proof from unperformed live acceptance. State current-tree
secret scan scope and whether historical repository scanning was performed.

## Security and license

[MIT](../../LICENSE); retain [third-party notices](../../NOTICE).
Use [SECURITY](../../SECURITY.md) for reporting, including private-channel
availability limits. No certification, response SLA or external-provider data
privacy guarantee is implied. Do not disclose a vulnerability before coordinated
handling or publish sensitive reproduction details in these notes.
