# SPEC-045 design handoff

Status: REVIEWED DESIGN — IMPLEMENTED AND LOCALLY VALIDATED

## Outcome and authority

Optional local repository navigation under the owner's
[SPEC-045](../../product/specs/SPEC-045-maintainer-knowledge-graph-codebase-navigation.md),
without application/schema change. Source/Harness remain authoritative.

## Selected design

`scripts/dev/graphify.sh` is original January glue around exact external
`graphifyy==0.9.74`, isolated through uv tool run. Build and update both invoke
explicit extract/code-only; query/path/explain use only existing root graph.
Status/version use shell only. Fixed arguments, no arbitrary backend flags,
clean child environment, no inherited keys, skill auto-refresh/logging disabled.
Ignore output and sensitive operator state; keep app/migrations/scripts/docs/tests
eligible. Preserve Harness bytes and append small optional/source-verifying
navigation guidance rather than upstream graph-first directives.

## Upstream audit and platform decision

Pinned source commit `0b60d47e6cd9338c51143f39f35b6c45c8453385` on v8; PyPI
0.9.74 matches 227 package files and three license/notice texts. External tool
is Apache-2.0 with legacy MIT portions noted upstream; no copied material.
Both project installers reproduced in isolated directories with network denied:
Codex writes a ~42 KB skill, eight references, version stamp, AGENTS guidance
and no-op hook; OpenCode a ~41 KB skill, eight references, stamp, AGENTS and
command-prefix plugin/config. All generated files remain outside January.
Git hooks also mutate Git config/.gitattributes and rebuild on commit/checkout;
none enabled. Upstream normal CLI can auto-refresh installed skills, so wrapper
explicitly disables that behavior. Query logging is also forced off.

## Validation design

Static stdlib contract plus offline tests against a fake uv: pin, dependency,
safe build/update, ignores, optionality, Harness, CI isolation, modes, missing
graph, fixed argument routing, environment controls and symlink rejection.
Optional index inspection also rejects force-added graph output; VCS-free
source manifests separately prove graph absence. Eight existing clean-inner
validators use a shared inventory fallback rather than assuming Git exists;
all existing selectors/assertions/migration legs remain intact.
Six required failure mutations plus additional boundary mutations in disposable
copies; no real Graphify/provider invocation in canonical checks.
Separate socket-denied compatibility build/query/path/explain with isolated
profile/cache and three source-verified repository questions.
Exact candidate Git modes/tree exported to depth-one and VCS-free contexts,
full workflow plus requested supplemental checks, graph absent/tool uninstalled,
owned Docker services only and inventory restoration. Final gate evidence lives
in handoff (private execution record omitted from this snapshot); executable results govern approval.

## Recovery and remaining limits

Preserve failed receipts, repair only authorized integration, retry full relevant
proof. Do not reset/stash/discard user work. Graph is syntactic, incomplete and
possibly stale; shortest paths are not runtime proof. Pin does not lock tool
transitives. Semantic workflows and copying upstream assets require fresh
review and are outside this design. Independent OpenCode audit follows local
candidate approval; no release/publication/SPEC-046 is authorized.
