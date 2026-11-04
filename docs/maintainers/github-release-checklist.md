# Owner GitHub source-release checklist

The repository is already public. Follow the
[post-publication procedure](post-publication-source-release.md) and
[acceptance ledger](../validation/OSS-001-acceptance.md). Historical SPEC-048
records remain unchanged. This checklist does not authorize publication.

- [x] Public repository ID, parentless root and existing main/ruleset observed.
- [x] Owner approved v0.1.0; it remains NOT YET PUBLISHED. No tag/date invented.
- [x] Private Vulnerability Reporting enabled with owner permission; API readback
  returned `enabled: true` on 2026-11-01. Recheck before publication.
- [ ] Exact source manifest/classifications, source modes and MIT/NOTICE reviewed.
- [ ] Complete locked runtime/development/transitive and container license review.
- [ ] Current-source and full reachable-history secret/privacy review complete.
- [ ] Exact-lock dependency advisory audit recorded without suppressed findings.
- [ ] Actual local-image scan/digest recorded separately; no image approval inferred.
- [ ] Full canonical Quality and supplemental synthetic/recovery checks pass.
- [ ] Single Alembic head `0026_conversation_feedback`; all 26 migrations retained.
- [ ] Clean source extraction/setup, authenticated setup contract, worker graph,
  readiness, backup/restore and upgrade evidence verified without live calls.
- [ ] Deterministic AI evaluation keeps PASS/NOT_EVALUATED/FAIL/ERROR distinctions.
- [ ] Independent OpenCode audit of exact approved private package/source complete.
- [ ] Exact final feature HEAD normally pushed after privacy gates; one Draft PR.
- [ ] Genuine GitHub Quality completed/success on exact final PR source SHA.
- [ ] Source archive contents, modes, provenance and checksums verified.
- [ ] Release notes/security limitations and source-versus-image decisions reviewed.
- [ ] Explicit owner release authorization obtained **after** Draft PR handoff.

Future owner actions (outside current authorization): merge through unchanged
protection, verify resulting main SHA/Quality and audit binding, create annotated
tag at that exact SHA, then publish the titled GitHub Pre-release with only
GitHub-generated source ZIP/tar.gz. Recheck absent version/tag first; never move
an existing tag. Reverify downloaded release source archives and record hashes.
No binary/package/image/model-weight publication or deployment is implied.
