# Bounded dependency license review

SPEC-044 review, 2026-10-02. This records installed metadata for the locked direct
Python runtime and development dependencies, not a legal opinion, exhaustive
transitive audit, model-weight license review or relicensing of dependencies.
Inspect again when the lock changes. All reported direct licenses below are
permissive; no obvious restrictive direct dependency was identified.

| Dependency | Installed locked version | Reported metadata |
| --- | --- | --- |
| alembic | 1.18.5 | License-Expression MIT |
| asyncpg | 0.31.0 | License-Expression Apache-2.0 |
| fastapi | 0.115.14 | MIT license classifier; no License-Expression |
| httpx | 0.28.1 | License BSD-3-Clause; BSD classifier |
| PyJWT | 2.13.0 | License-Expression MIT |
| pydantic-settings | 2.7.1 | License-Expression MIT; MIT classifier |
| redis | 5.3.1 | License MIT; MIT classifier |
| sqlalchemy | 2.0.51 | License MIT |
| uvicorn | 0.34.3 | License-Expression BSD-3-Clause |
| mypy (development) | 1.14.1 | License MIT; MIT classifier |
| pytest (development) | 8.3.5 | License MIT; MIT classifier |
| ruff (development) | 0.9.10 | License MIT; MIT classifier |

No direct dependency lacked all license metadata. This is the Redis **Python
client**, not a blanket claim about every Redis server release. PostgreSQL,
Redis and optional Qdrant containers, Python/base-image packages, uv, local
model weights and provider services retain their own licenses/terms. Do not
apply the project's MIT grant to them; downstream image/model redistribution
requires reviewing and retaining their supplied notices. Model downloads and
provider account terms are operator choices, not project license grants.

## Installed upstream material

`.harness-core/manifest.json` identifies installed Repository Harness core
0.1.7 and source hashes. Its installed `.agents/skills` Python/docs, base copies,
workflow/templates and index portions are third-party material. The upstream
[MIT LICENSE](https://github.com/hoangnb24/repository-harness/blob/e765792b635b4d5e3e5fc0578f82f9ca5dea2681/LICENSE)
contains `Copyright (c) 2025 Hoang Nguyen`. [NOTICE](../../NOTICE) preserves that
exact upstream license and scopes it to the installed portions; the project's
`Copyright (c) 2026 hzjanuary` does not replace upstream ownership.

NOTICE exists for this concrete copied-material obligation, not because MIT
requires a separate NOTICE filename. No per-file boilerplate, CLA or custom
license restriction is added. Generated migration/test data is repository
material and must remain synthetic; further copied content needs its own source
and license review before inclusion.
