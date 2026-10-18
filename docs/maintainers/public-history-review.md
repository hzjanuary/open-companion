# Public reachable-history review

This is a local read-only tool contract, not an inherited private audit.
Owner-specific history inventories, dispositions and receipts are excluded.
See the [publication procedure](first-public-publication.md).

## Tool contract

From the repository root, run:

```bash
uv run python scripts/public_release/audit_history.py --root .
```

Default scope is HEAD and every locally present ref. Explicit repeated `--ref`
arguments must include all refs and HEAD. The tool is local/read-only and does
not fetch or call GitHub. It verifies non-shallow/full object coverage, rejects
partial/grafted/replaced/alternate history, missing objects, uninspected
submodules/noncommit refs and exceeded bounds. Limits are 100,000 objects,
16 MiB per object, 256 MiB total content and 60 seconds per Git read. Exceeding
a bound requires explicit review; it is never a silent content exclusion.

Exit 0 means no unresolved automatic finding, with owner and independent
publication gates still required. Exit 1 means review required; exit 2 means
coverage incomplete. A shallow clone or source archive cannot claim complete
historical review. The synthetic unit tests work without January Git history.

Output contains object IDs, path SHA-256 fingerprints, categories and line
numbers, never matched text, raw paths/identities or Git stderr. Detectors cover
Telegram/provider/GitHub/cloud token patterns, JWTs, private keys, credential
assignments/URLs, risky env/key/dump/log/archive paths, platform identifiers,
private-record structures and personal checkout paths. Binary/large content
is accounted for explicitly. Human contextual review remains necessary.

`--dispositions FILE` accepts JSON keyed by the exact finding ID, each with
`disposition` and a nonempty private review `reason`. Allowed dispositions are
`synthetic-fixture`, `documented-example`, `false-positive`, and, for personal
checkout paths only, `owner-consent-required`. They never remove the automatic
detection. A changed object requires new review; stale IDs fail. Do not publish
raw values in reasons. No path-wide or token-family allowlist is installed.

## VCS-free source and future public history

SPEC-048 stages no .git directory and initializes no repository. Running this
tool on the source archive must report COVERAGE_INCOMPLETE and exit 2: expected
negative coverage proof, not a synthetic-test failure. No full-history or
secret-absence claim can be inherited from an archive.

Synthetic tests create disposable repositories outside the final snapshot with
synthetic metadata and attack content. Those isolated test commits contain no
original history and are not publication actions. Preserve coverage assertions.

After independent audit and separately authorized owner creation of a NEW root
commit, audit all new public refs and metadata. Retrieve the exact GitHub
noreply address from Settings, verify author AND committer, and review current
source. Do not import private history or assume owner consent to exposure.
Unreachable/unfetched objects, GitHub issues/logs/artifacts and external systems
remain separate review surfaces.
