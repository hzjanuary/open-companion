# First public publication

Owner procedure only. **v0.1.0 is approved and NOT YET PUBLISHED.**
The planned public repository is https://github.com/hzjanuary/open-companion.
No original private history is to be imported. Source builds remain canonical.

1. Commission an independent OpenCode audit of the exact SPEC-048 manifest,
   classifications, redacted findings, changes and validation receipts. Stop
   for unresolved Critical/High findings, missing proof or a required red gate.
2. Confirm a real private vulnerability disclosure channel before distribution;
   review branch protection, Actions permissions and Issues/Discussions.
   SECURITY.md does not assert an already available private channel.
3. Review every staged file and mode. Retrieve the EXACT GitHub-provided noreply
   address from GitHub Settings → Emails; verify intended public author and
   committer names and that address locally. Never invent a noreply address
   or reuse private global Git email configuration.
4. Only in a separately authorized owner session, initialize a NEW repository
   from the approved manifest. Do not copy private .git, refs, objects, hooks,
   remotes or configuration. Configure the reviewed name and exact noreply
   address locally for BOTH author and committer. Review inherited signing
   and hooks before allowing them to run.
5. Inspect the full index, modes and commit environment, including overrides
   GIT_AUTHOR_EMAIL/GIT_COMMITTER_EMAIL. Create one new root commit only with
   separate owner authority; verify it has no parents and both identities use
   the approved noreply address. Re-run current-file and full reachable-history
   review on the NEW repository.
6. Connect and push to the approved target only with separate owner authority.
   Wait for completed/success Quality on that exact new SHA, correct branch
   and event. Older private baseline CI cannot approve these filtered sources.
7. Recheck independent audit, source archive, executable modes, MIT/NOTICE,
   notes, migration head and local/remote evidence. Owner separately authorizes
   Private → Public; copied public data cannot be recalled by reversing visibility.
8. In a separately authorized owner session, create and verify the annotated
   v0.1.0 tag at the verified SHA, push it and publish reviewed GitHub Release
   notes/source. Record actual dates, URLs and targets only afterward.

No Git init, commit, remote creation, push, tag, release, upload, visibility or
settings change is authorized during staging. The VCS-free history scanner
correctly returns COVERAGE_INCOMPLETE (exit 2); synthetic tests remain required.
Synthetic Git test repositories live outside the final snapshot and contain
no original private history.

If credentials/private records are found, stop and report only safe metadata
privately. Issuer rotation/revocation and incident recovery need owner handling;
removing a line does not revoke a credential. No managed SaaS, official registry
image, LTS or guaranteed downgrade is offered. See [release process](release-process.md),
[checklist](github-release-checklist.md), [history tool](public-history-review.md),
[draft notes](../releases/first-public-release-candidate.md),
[upgrades](../runbooks/self-hosted-upgrades.md) and [SECURITY](../../SECURITY.md).
