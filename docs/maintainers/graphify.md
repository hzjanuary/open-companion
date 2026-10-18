# Optional Graphify repository navigation

## Purpose and scope

Graphify helps maintainers locate symbols, imports and relationships before
reading source. It is optional developer tooling, not January application
runtime, a Telegram capability, explicit/semantic memory, RAG, PostgreSQL
authority or a Qdrant replacement. Contributors, self-host operators, startup,
workers, migrations and canonical Quality do not need it.

Repository source and Harness remain authoritative. A graph is local, derived,
rebuildable and non-authoritative. Graphify helps understand the repository; it
does not define it. User requests take precedence, followed by repository/Harness
authority, optional graph navigation, then source verification. Missing or stale
graphs never block work. After meaningful source changes a maintainer may run
update explicitly; even a fresh graph cannot prove runtime/product behavior.

## Audited upstream and pin

Selected package: `graphifyy==0.9.74` (CLI `graphify`, double-y package name).
Independently checked on 2026-10-03 against
[PyPI 0.9.74](https://pypi.org/project/graphifyy/0.9.74/) and
[Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify), default branch
`v8`, audited commit `0b60d47e6cd9338c51143f39f35b6c45c8453385`.
The wheel SHA256 is
`7d7f2475be6f3dd5723743989d1a5a02f323f715ff6938cff999f3014cde41c5`.
All 227 packaged source/assets matched that commit byte-for-byte. No upgrade was
necessary at the 2026-10-03 audit: the version was then current and its selected
local paths passed the source audit. A recovery check on 2026-10-06 found PyPI
0.9.77. Its package diff and license/notice boundary were reviewed: changes
include path traversal/ambiguity, extraction/dedup and cache handling, generated
skill workflows and git-hook path validation. Those hooks/skills are not enabled
here. Keep the audited and compatibility-tested 0.9.74: the newer release is not
required by this bounded interface and has not passed full upgrade qualification.
Do not automatically chase it. This pin freezes Graphify itself, not all
transitive dependency versions; isolated resolution can vary. Re-audit upgrades
explicitly.

Reviewed upstream README, pyproject, LICENSE, LICENSE-MIT, NOTICE, CLI dispatch,
detector, query traversal, watch/update, installers, hook generation, profile
refresh and query logging. Source links use the
[audited commit](https://github.com/Graphify-Labs/graphify/tree/0b60d47e6cd9338c51143f39f35b6c45c8453385),
not a floating branch as an executable input.

## Install/run mechanism

Use Bash and the same uv resolution as January's scripts (PATH uv, or existing
`.tools/uv`). No global Graphify installation, account or API key is needed:

```bash
./scripts/dev/graphify.sh version
./scripts/dev/graphify.sh status
./scripts/dev/graphify.sh build
```

`version` reports the selected pin, not a discovered installed executable.
`status` only checks for a usable graph file and says freshness is unknown.
Both work without uv/Graphify/network/Git. Other commands use isolated
`uv tool run --from graphifyy==0.9.74 graphify ...`. First resolution can download
the pinned package and dependencies from the package index; this is a maintainer
action separate from canonical validation, not a repository-content upload.
With the tool cached, `UV_OFFLINE=1` prevents uv network resolution. If unavailable
offline, uv fails; it never falls back to an unpinned executable.

The wrapper discovers its root from its location and also works in a source
archive without `.git`. It accepts only the commands below, checks arity, refuses
option-looking query/node inputs and symlinked output, and always uses root
`graphify-out/`. A clean child environment drops inherited provider credentials
and Graphify overrides. It disables skill auto-refresh, external query logging
and backend tips. It never installs skills/hooks, changes Docker, or mutates
application data. Query/path/explain may update upstream's local query timestamp.

## Build and update

```bash
./scripts/dev/graphify.sh build
./scripts/dev/graphify.sh update
```

Both execute the audited `graphify extract . --code-only` path: local tree-sitter
AST extraction; document/media semantic work is skipped and no model key is
required. Upstream CLI `update` also uses `_rebuild_code` locally in this version,
but assistant `/graphify --update` can include semantic extraction. January uses
the explicit extract flag for both commands to keep that distinction unambiguous.
Upstream extract uses manifests/cache for incremental work. It can preserve a
pre-existing semantic layer; this integration does not create one or certify
the provenance of an operator's existing graph. Use a fresh local output when
changing extraction policies; inspect before removing any valued state.

## Query, path and explain

```bash
./scripts/dev/graphify.sh query 'Telegram ingress durable inbox'
./scripts/dev/graphify.sh path 'response_planning_worker.py' 'GovernedModelProvider'
./scripts/dev/graphify.sh explain 'SqlAlchemySemanticMemoryRepository'
```

These commands require `graphify-out/graph.json`. If absent, they exit nonzero
with build guidance before invoking uv. They do not silently build or select a
semantic backend. Audited query is lexical ranking plus graph traversal; path
is graph path search; explain displays node/source/neighbors. They do not ask a
model to answer. Search may be ambiguous; use path-qualified identifiers from
results when labels collide. A graph path expresses syntactic connectivity,
not necessarily a runtime call chain. Verify the relevant source and tests.

## Codex and OpenCode

Both use the small original optional-navigation guidance in `AGENTS.md` and
this wrapper. No generated skill, hook, plugin or platform configuration is
included. No parallel-agent feature or assistant model is required.

The pinned upstream installers were actually reproduced in temporary projects
with the January Harness block, a temporary profile and denied network sockets:

| Installer | Generated project files | January decision |
| --- | --- | --- |
| `install --project --platform codex` | AGENTS section, `.codex/hooks.json`, `.codex/skills/graphify/SKILL.md`, `.graphify_version`, eight reference files | Do not copy/install; hook calls `graphify hook-check` (intentional no-op); ~42 KB skill includes broad extraction workflows. |
| `install --project --platform opencode` | AGENTS section, `.opencode/opencode.json`, `.opencode/plugins/graphify.js`, skill/version/eight references under `.opencode/skills/graphify/` | Do not copy/install; ~41 KB skill and plugin exceed the minimal local navigation scope. |

Both installers preserved the Harness bytes in the isolated reproduction, but
appended graph-first instructions and automatic refresh expectations that are
inappropriate for optional January tooling. Codex has no additional useful
hook behavior here. The OpenCode `tool.execute.before` plugin checks graph
presence and prefixes the first Bash command with a reminder. Its inspected
body makes no network calls or source writes and never permanently blocks a
tool, but it still rewrites commands and installs extra config without useful
value for this contract. Neither is enabled in January.

Upstream git `hook install` writes post-commit/post-checkout hooks and registers
a graph merge driver in Git config and `.gitattributes`; that can rebuild derived
state on commits/checkouts. It is not enabled. No automatic pull/merge/build or
global Git alias is added. Do not run upstream installers on the candidate.

## Privacy, ignores and derived state

Code-only is local AST extraction according to the audited source. Graphify as
a whole is not always offline: optional semantic docs/media workflows can use
configured local or external model backends, and URL/cloud/database features
have separate I/O. Those modes are outside this wrapper and require explicit
maintainer intent, a new privacy review and appropriate credentials. Canonical
validation never executes Graphify or uploads repository content.

Upstream honors `.gitignore` and `.graphifyignore`; the latter adds exclusions
for env files (including env templates), virtualenvs, tools, runtime/local state,
backups, credential stores, private-key files and the output itself. Excluding
env templates avoids treating them as source content; normal application,
migrations, scripts, docs and tests remain eligible. Detector also filters
sensitive file names and defaults to not following symlinks. Ignore rules are
an explicit boundary, not a universal secret detector: review newly added local
material before building. Never build over real credentials or private data.

Everything under `graphify-out/` stays ignored: graph JSON/HTML/report, cache,
cost records, work memory, learning overlays, absolute-path markers and query
timestamps. Docker context excludes output, agent-local state and integration
scripts. Generated graphs are not shared/committed, required inputs or Quality
artifacts. Dirty or stale ignored output is not a Quality failure. January's
public source archive works without a graph, tool install or Git history.

## Upgrade procedure

1. Inspect exact proposed upstream package/source identity, licenses and
   dependency changes before editing the pin; do not automatically chase releases.
2. Re-audit default/update/query/explain behavior, env overrides, ignores,
   auto-refresh/logging, Codex/OpenCode installers and git hooks in a temporary
   project. Record package digest and immutable source commit.
3. Update the wrapper, contract expectations and guide together. Run hermetic
   tests including unsafe-build/dependency/CI/Harness failure injections.
4. Repeat a separate credential-free code-only compatibility smoke, verify
   useful findings against source, and run appropriate January Quality without
   graph output. Never add Graphify to the application lock/runtime or CI.

## Uninstall and cleanup

No assistant or Git integration was installed, so none needs uninstalling.
To discard the local graph, first inspect its contents and move the specific
root `graphify-out/` directory to a chosen backup location, or remove only that
reviewed derived directory. The next build recreates it. Do not run broad cleanup
or delete unrelated tools/data. uv's tool/cache retention is managed by uv;
inspect `uv tool list` before removing an independently installed tool. A prior
manual upstream install has separate config/hooks; review its exact generated
files and use the matching pinned project's uninstall procedure, preserving
Harness and unrelated hooks. The January wrapper does not perform cleanup.

## Troubleshooting and proof

- Missing graph: build is optional; continue reading source or build explicitly.
- Missing uv/cached package: status/version still work; install uv separately or
  allow explicit maintainer package resolution. Canonical Quality needs no Graphify.
- Empty/ambiguous results: check spelling, source scope and stale manifests;
  inspect source directly. Unsupported AST languages are not proof of absence.
- Output symlink: use a regular local output directory; do not force through it.
- Extraction failure: preserve diagnostics after privacy review; do not switch to
  a provider backend to make a local build pass.

`./scripts/validate-graphify-integration.sh` checks January's source contract and
tests wrapper calls against a fake uv executable, offline. It does not test
upstream internals, download/install Graphify or build a graph. Failure injection
covers pin/runtime-dependency/ignore/semantic-build/Harness/CI violations. Full
candidate and compatibility results are recorded in the
SPEC-045 handoff (private execution record omitted from this snapshot).

The validator reads the Git index for force-added graph output when Git and
repository metadata are present; ignored dirty/stale graphs still pass.
VCS-free archive contents are proven separately against the candidate tree.
Eight existing validators share a clean-copy inventory helper so their inner
proofs also work without Git metadata. It preserves the four committed env
templates, excludes operator env files/local ignored state, and fails closed
on unsupported ignore negation instead of silently reducing source coverage.

## License boundary

January's [MIT LICENSE](../../LICENSE) and [NOTICE](../../NOTICE) are unchanged.
Graphify is independently installed external Apache-2.0 tooling. Its
[NOTICE](https://github.com/Graphify-Labs/graphify/blob/0b60d47e6cd9338c51143f39f35b6c45c8453385/NOTICE)
also identifies legacy MIT portions; the package includes LICENSE, LICENSE-MIT
and NOTICE. January vendors no Graphify implementation, skill, plugin or
generated instruction text, so no upstream-derived material requires a new
January redistribution notice. Original January glue/docs use the repository
license; simply naming the external command does not relicense January.
Any future copying/distribution needs a specific attribution/license review.
