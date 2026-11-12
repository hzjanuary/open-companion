# Post-publication source release

Target: **January v0.1.0 — Initial Self-hosted Telegram AI Companion Source Preview**.
This is a source-only GitHub Pre-release proposal; v0.1.0 is NOT YET PUBLISHED.
The owner retains the final release decision. No live Telegram, provider,
Zalo or LLM judge request is part of synthetic source acceptance.

## Existing public baseline

Repository https://github.com/hzjanuary/open-companion, ID `1423511659`, is
public with default branch `main`. At the OSS-001 start, main was
`612f89c6724261873d38cfa9a9639eb5836cb41a`; Quality run `40069948712`
completed successfully on that SHA. The original public root
`069642473d6a39824b7a5ccf9c844cb8e6c4f354` has no parent. Its author and
committer use the observed GitHub noreply identity. The existing merge has
owner-acknowledged personal author metadata; preserve it without repeating the
address in reports. Use the observed owner noreply identity for new commits.

Active ruleset `protect-main` (ID `25766062`) requires a pull request and strict
`quality`, prevents deletion/non-fast-forward updates and has no bypass actors.
Preserve it. API inspection on 2026-11-01 found no tags or Releases. Recheck
these facts before publication; never move or overwrite an existing version.

## Candidate sequence

1. Work on `feat/oss-001-january-source-release`, preserving existing main,
   root, refs, operator state and all 26 migrations. Record exact source hashes,
   per-file classifications/modes, changes and upstream notices.
2. Complete [acceptance](../validation/OSS-001-acceptance.md): current and
   complete reachable-history review, pinned dependency advisory audit,
   separate actual-image scan, full canonical Quality and supplementary
   synthetic integration/recovery checks. Preserve failures and scan findings.
3. Verify source archives and clean extraction/install, including executable
   scripts, LICENSE, NOTICE, migrations and tests. Never include private
   configuration, conversations, backups, model weights or execution receipts.
4. Obtain an independent OpenCode audit of the exact owner-approved private
   SPEC-048 package and exact proposed source. If the package path/export is
   unavailable, mark this BLOCKED; public handoff text is no substitute.
   Resolve uncertain ownership, required red gates and Critical/High findings.
5. After local publication privacy gates pass, review all changed files/modes,
   commit with approved noreply metadata and normally push the feature branch.
   Open one Draft PR against main. Run genuine GitHub Actions and verify
   completed/success `quality` on the final PR HEAD SHA; distinguish any merge
   test SHA. A baseline run cannot verify changed source.
6. Record exact SHA, runs, reviewed source archive hashes and independent audit
   binding. Changes after review require affected proof and renewed review.
   Stop at the Draft PR and request explicit owner release authorization.

## Separate owner publication procedure

Only after owner authorization: merge through existing protections, verify
Quality and source review on the resulting main SHA, create the approved
annotated `v0.1.0` tag at that verified SHA, and publish a GitHub **Pre-release**
with reviewed notes and GitHub-generated source ZIP/tar.gz. A changed merge SHA
needs verification; approval of an earlier PR SHA is not inherited blindly.
Record the resulting tag target, artifact checksums and actual publication date.
These are future owner steps, not actions authorized by OSS-001 execution.

No official binary, package, prebuilt Docker image, model weights or deployment
is included. A local Docker build and source approval never approve image
publication. Keep its digest, licenses, raw scan results and unresolved OS or
Python vulnerabilities in a separate image decision. Unresolved image findings
require an explicit owner source-only risk decision and security notice.
