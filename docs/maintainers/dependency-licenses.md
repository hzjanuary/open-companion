# Dependency and installed-source license inventory

Engineering review, 2026-11-01; metadata/license hashes reverified 2026-11-04.
This is not a legal certification. January application
source is independently developed according to the owner's declaration.
Copyright (c) 2026 Hoang Nguyen; standard [MIT grant](../../LICENSE).
Git author metadata alone does not establish ownership. This grant does not
relicense dependencies, copied maintainer tools, containers, providers or models.

## Complete locked Python scope

The [machine-readable inventory](../validation/OSS-001-python-licenses.json)
records all 41 third-party packages in the current `uv.lock`: direct runtime,
development, transitive and OS-conditional dependencies. Each entry records exact
version, runtime/development scope, dependency edges, reported license expression,
legacy license/classifiers, metadata SHA-256 and shipped license-file hashes.
40 distributions were inspected in the locked Python 3.12.9 environment. The
Windows-conditional colorama 0.4.6 wheel was fetched from its exact lock URL and
verified against the lock's SHA-256 before metadata inspection; it was not
installed on Linux. The inventory embeds the exact lock SHA-256. Regenerate and
review it when the lock changes; old direct-only tables are superseded.

Reported license families include MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause,
PSF-2.0 and MPL-2.0. Preserve component distinctions: certifi reports MPL-2.0;
greenlet reports MIT AND PSF-2.0; packaging reports Apache-2.0 OR BSD-2-Clause;
typing-extensions reports PSF-2.0. uvloop's legacy metadata says MIT while its
classifiers also include Apache: retain its shipped notices and bundled libuv
obligations rather than describing everything as MIT. Metadata is a provenance
input, not proof of exhaustive bundled-code ownership or license compatibility.

The inventory was produced using `importlib.metadata` after
`uv sync --all-groups --locked`, reading only exact-version distribution METADATA
and license files; missing metadata is not silently treated as MIT. A separately
generated CycloneDX SBOM and advisory results supplement this inventory. Audit
and inventory tooling dependencies are tooling, not January runtime dependencies.

## Container, build-tool and model boundaries

| Component | Source/version boundary | License/obligation boundary |
| --- | --- | --- |
| Python base | Dockerfile `python:3.12-slim`; mutable tag, record actual digest per build | Python PSF license and notices; Debian OS packages each retain their own terms, including copyleft components. Review actual image SBOM and `/usr/share/doc/*/copyright`. [Official image license guidance](https://hub.docker.com/_/python). |
| PostgreSQL | Compose `postgres:16-alpine`; record digest/server version | [PostgreSQL License](https://www.postgresql.org/about/licence/); Alpine and bundled libraries have separate licenses. |
| Redis server | Compose `redis:7-alpine`; exact minor/digest matters | [Upstream terms](https://redis.io/legal/licenses/): 7.2 and earlier BSD-3-Clause; 7.4 series RSALv2 OR SSPLv1. Do not mistake the MIT Python client for the server or apply Redis 8 terms to Redis 7. Retain selected version's notices. |
| Qdrant | Optional `qdrant/qdrant:v1.13.4` | [Apache-2.0 source license](https://github.com/qdrant/qdrant/blob/v1.13.4/LICENSE); image OS and bundled dependencies retain their own licenses. |
| uv | Dockerfile/CI 0.6.5 | [MIT](https://github.com/astral-sh/uv/blob/0.6.5/LICENSE-MIT) OR [Apache-2.0](https://github.com/astral-sh/uv/blob/0.6.5/LICENSE-APACHE); build/contributor tooling, not a runtime service. |
| Ollama | Optional separately operated local model server; not bundled | [Ollama MIT source](https://github.com/ollama/ollama/blob/main/LICENSE) does not grant licenses to downloaded model weights. Review the actual selected release and its dependencies. |
| Model weights | No model or weights supplied/downloaded by this release | Model-specific license, acceptable-use, redistribution and commercial terms remain separate. Record model identity and terms before use; no blanket MIT claim. |
| Hosted providers / Telegram | External services, not copied source | Operator accounts, API/service terms and data processing boundaries remain separate from project licensing. |

Source-only distribution references container images; it does not redistribute
an official prebuilt January image. A local image build/scan does not authorize
registry publication. Exact image identities, package inventory, OS/license
results and vulnerability findings belong in the separate image ledger. Mutable
tags do not imply reproducible digests or future security approval.

The [machine container inventory](../validation/OSS-001-container-inventory.json)
records actual observed digests, OS/Python package license metadata, PostgreSQL
16.15, Redis 7.4.11 and optional Qdrant v1.13.4 contents. Qdrant's upstream image
also includes Node.js dashboard dependencies, scoped to that optional image.
The local January image has 45 unresolved HIGH OS findings in the recorded
scan; image publication/security approval remains withheld. Full findings,
fixed-version availability, scanner/DB identity and raw-result hash are retained
separately from the zero-advisory exact-lock Python source audit.

## Isolated audit and optional navigation tooling

Gitleaks 8.30.1 is MIT; Trivy 0.76.1 and pip-audit 2.9.0 are Apache-2.0.
Their pinned verification identities and upstream license links are recorded
in the container inventory. They run in isolated tooling environments and
are not added to the application lock or runtime. Optional external
`graphifyy==0.9.74` is Apache-2.0 with legacy MIT portions retained in upstream
LICENSE-MIT/NOTICE; see the [audited navigation boundary](graphify.md#license-boundary).
January vendors its own wrapper, not the upstream implementation. The complete
41-package inventory covers the application lock; it does not silently claim
that every separately installed tool's transitive bundle is January-owned.

## Installed Repository Harness core 0.1.7

[NOTICE](../../NOTICE) retains the exact upstream MIT grant and
`Copyright (c) 2025 Hoang Nguyen`, verified upstream at
`e765792b635b4d5e3e5fc0578f82f9ca5dea2681`. Installed material consists of
`.agents/skills`, original `.harness-core/base` copies, manifest-listed generic
workflow/index/templates and Harness portions of AGENTS.md. Product-specific
adaptations retain upstream obligations for copied portions. The manifest's
upstream hashes must not be confused with hashes of adapted current files.

These are optional maintainer/development tools, not runtime dependencies.
No Harness files are removed in OSS-001. No external Harness repository is
modified or needed to build/test January. No blanket ownership inference,
per-file extra restriction, CLA or relicensing is added. Historical specs,
plans and handoffs remain evidence of earlier stages, not independent audit
approval or proof of current release state.
