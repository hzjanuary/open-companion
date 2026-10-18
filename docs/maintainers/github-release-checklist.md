# Owner GitHub release checklist

This is a future owner procedure, not agent authorization. SPEC-048 creates no
commit, push, tag, GitHub Release, registry image or deployment. Follow the
[release process](release-process.md) and the
[first-public owner procedure](first-public-publication.md); stop on an unproved gate.

- [ ] Exact manifest audited; future new root SHA selected only after separate
  owner authority; worktree/index clean; no unexplained files.
- [ ] Independent audit passed; no unresolved Critical or High finding.
- [ ] Full local Quality passed in meaningful CI order, with synthetic services
  and no secrets; no removed/weakened checks or masked failures.
- [ ] Owner-pushed exact SHA has completed successful remote GitHub Quality;
  a prior baseline run is insufficient for a changed candidate.
- [ ] Standard MIT LICENSE, metadata and README agree; third-party notices
  retained; source dependencies reviewed for license concerns.
- [x] Owner approved v0.1.0; package metadata is 0.1.0. NOT YET PUBLISHED;
  no tag or publication date is invented.
- [ ] CHANGELOG and release notes updated for that version.
- [ ] Single Alembic head recorded; migration/config/breaking changes explicit.
- [ ] Canonical quickstart checked from the exact source, offline doctor and
  self-host validator pass; live acceptance is separate and authorized if used.
- [ ] Backup/restore/upgrade guidance linked; downgrade limitations explicit.
- [ ] Current candidate secret/private-data scan reviewed; historical audit
  scope stated truthfully. Private vulnerability reporting/contact confirmed
  before public distribution, without publishing an exploit or inventing contact.
- [ ] [Reachable history](public-history-review.md) rechecked after the owner
  commits publication work; no unresolved high-risk content. New root history contains only approved GitHub noreply metadata; no
  private history, personal email or personal checkout path is imported.
- [ ] Owner reviewed branch protection, Issues/Discussions, Actions permissions
  and private vulnerability reporting settings before public distribution.
- [ ] Complete Git source archive, Git modes and extracted executable behavior
  checked; fresh/shallow/VCS-free proofs pass without ignored dependencies.
- [ ] Optional image build is from the same source; actual image ID/digest and
  platform recorded. No nonexistent official registry image is advertised.
- [ ] Owner explicitly authorized repository visibility and publication.
- [ ] Owner understands returning visibility to private cannot retract clones.
- [ ] Owner separately creates an annotated approved tag at the verified SHA,
  pushes it, then verifies tag object and target.
- [ ] Owner publishes GitHub Release with that tag, reviewed notes and source.

Until the last actions are actually observed, say candidate or verified
baseline, not tagged/published release. Never silently move an existing tag.
