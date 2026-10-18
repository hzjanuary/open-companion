# SPEC-043 — Open-Source Self-Hosted Distribution and First Run

Date: 2026-10-01

Status: APPROVED SELF-HOST DISTRIBUTION SPEC

This approves the bounded operational contract, not implementation readiness,
public licensing, a deployment, or live Telegram/provider acceptance.

## Authority and continuity

The Product Owner's SPEC-043 establishes OPEN SOURCE / LOCAL-FIRST /
SELF-HOSTED as the future distribution direction. The person running January
is its self-host operator. A central production organization, commercial
provider, corporate approval, formal on-call, external monitoring service,
container registry, hosted account system, billing system, and managed SaaS
are not requirements.

SPEC-041 remains complete for release/operational readiness; SPEC-042 remains
complete for its promotion-package scope. Their specifications, completed
plans, handoffs, and audits are historical records and must not be rewritten.
Their stronger centralized production model remains available to downstream
operators who choose it. The policy evolution is chronological, not a claim
that earlier decisions were mistakes.

Development baseline: `private-source-checkpoint-omitted`.
Prior exact-SHA Quality: `36755636502`, main/push/completed/success.
Historical SPEC-042 release source `private-source-checkpoint-omitted`
is not the SPEC-043 development baseline.

Migration: NONE. Single source head: `0026_conversation_feedback`.
New product behavior, entities, routes, Telegram commands, provider
capabilities, and evaluation scenarios: NONE. Zalo stays frozen.

## Outcome and user stories

A new user can clone, configure, start, verify, and use the existing Telegram
companion without traversing historical production specifications. Polling is
the simplest ingress path. Webhook and stronger deployment practices are
explicitly optional. Every advertised command must exist and be proved.

- As a local self-hoster, I can identify the minimum configuration, establish
  my own authority, and run the complete bot rather than only a healthy API.
- As a VPS operator, I can run one headless Compose deployment with safe
  network defaults, durable state, backup/restore, and a truthful upgrade path.
- As a contributor, I can run credential-free Quality on a shallow checkout
  or VCS-free export without a developer virtualenv or paid external service.
- As a user, self-hosting does not weaken my privacy, safety, tenant scope,
  current-lifecycle authority, erasure, or provider-admission protections.

## Supported profiles

These are documentation/operational profiles, not new `Settings.environment`
values. Existing environments remain `local`, `test`, `staging`, `production`.
The [canonical deployment policy](../self-hosted-deployment-profile.md)
defines their engineering obligations.

| Profile | Required services/config | Network | Persistence and backup | Security |
| --- | --- | --- | --- | --- |
| `LOCAL_DEVELOPMENT` | Python 3.12/UV application; project PostgreSQL; Redis for delivery/rate/concurrency; selected workers/config when testing a bot | loopback dependency ports; outbound only for deliberate live use | PostgreSQL volume; casual synthetic testing backup optional | local ignored secrets, no debug/echo with real sensitive traffic, fake boundaries in Quality |
| `LOCAL_SELF_HOST` | Docker/Compose; PostgreSQL, Redis, one migration owner, API and complete core workers; bot/provider, authenticated operator and persisted enforced policy configuration | loopback API, internal data services; outbound Telegram and selected provider | durable PostgreSQL; Redis coordination; persistent personal backup recommended | non-root application; safety/privacy/rate/concurrency/enforcement/retention remain active |
| `VPS_SELF_HOST_POLLING` | same core topology and configuration as local Compose; exactly one poller | outbound Telegram/provider connectivity; operator access only; no Telegram inbound HTTP, DNS, TLS or proxy requirement | persistent PostgreSQL; meaningful-data backup strongly recommended | restrict host access/secrets; no public data services or anonymous control plane |
| `VPS_SELF_HOST_WEBHOOK` | same core without poller; webhook secret and configured HTTPS URL; operator-selected TLS ingress | public HTTPS with valid TLS for the webhook; private/loopback data services and control plane | same as polling | authenticate webhook; exactly one ingress owner; deliberate lifecycle operations only |

Optional across profiles: Qdrant and embedding/index workers, summaries,
knowledge/RAG, scheduling, media, TTS, metrics export and external monitoring.
Enabling an optional feature requires its actual configuration, matching
workers/profile, provider capabilities and current authority. Disabled
optionals must not become first-run/readiness dependencies.

## Functional and operational requirements

### First run and configuration

1. Document the shortest complete polling path, separating dependency/schema
   startup, authenticated setup, runtime startup, readiness and optional live
   user acceptance. An API alone is not a functioning companion.
2. Use the actual `Settings` names and dependencies. Keep the complete
   244-setting `.env.example` inventory and stricter production validation;
   present a smaller first-run surface without requiring manual editing of
   all settings. Configuration defaults do not authorize spend or new policy.
3. Telegram token plus a selected hosted provider credential are external
   credentials for remote text chat. Ollama is supported without a provider
   key but needs an accessible local model. Database and JWT secrets are
   local operator secrets, not additional paid accounts. Webhook/TTS secrets
   are conditional; ordinary non-OpenAI text chat needs no OpenAI TTS key.
4. Establish real tenant/Assistant/connection authority and persisted provider
   admission before starting ingress. Do not depend on a migration fixture,
   disable governance, or bypass existing authenticated controls. An
   operational setup facade may reuse existing APIs/services, never implement
   new domain behavior or silently revive disabled/retired resources.
5. Operator-selected prices, finite hard budgets, health thresholds and data
   eligibility remain explicit choices. Do not fabricate universal provider
   prices, model parity or permissive spend limits to make onboarding pass.

### Runtime and network

6. Compose must supply all required real modules, healthy dependencies, a
   bounded migration command, persistent PostgreSQL and graceful worker
   shutdown/restart behavior. No unrelated host service may supply a hidden
   dependency. Build locally; no mandatory registry or GUI.
7. Prefer internal data services; native-development ports bind loopback.
   Existing host-port overrides remain usable. Never stop unrelated stacks,
   expose data stores publicly, disable TLS verification, or relax Docker
   socket permissions to pass a test.
8. Polling must need no public infrastructure and preserve durable atomic
   cursor/batch acceptance, deduplication, one ingress owner and bounded
   recovery. The poller refuses an installed webhook and never removes it.
9. Webhook is optional and needs an exact configured URL, HTTPS/TLS, secret,
   authenticated bounded parsing and single ownership. Registration/deletion
   remains explicit; startup does not mutate DNS or Telegram webhook state.
10. `/live` proves process life; `/ready` proves exact PostgreSQL head and
    required Redis. Neither substitutes for bot identity, provider policy,
    optional feature workers or durable end-to-end evidence.

### Operators, state and security

11. The operator/control API stays authenticated. Provider `enforce` mode
    requires its functionality and recovery worker, but not public exposure
    or a corporate identity service. Deployment authority and tenant roles
    retain their distinct existing scopes.
12. PostgreSQL is authoritative; Redis is transient coordination; Qdrant is
    derived/rebuildable. Document voice/media artifact persistence accurately,
    including PostgreSQL voice bytes and bounded retention/erasure, without
    inventing a permanent media volume.
13. Provide practical backup tiers and the supported logical backup flow.
    Restore requires quiescence, exact revision/authority checks, post-backup
    erasure reconciliation and derived-state rebuilding before traffic.
    Redis/Qdrant backups alone are not an authoritative backup.
14. Upgrade guidance includes pinning a tag or exact SHA, release/config
    review, backup, preflight, single migration owner, restart, readiness and
    smoke. Never promise database downgrade or automatic rollback compatibility.
15. Secrets stay in restricted ignored local operator files/runtime injection,
    never images, source, logs, diagnostics or public reports. Preserve
    fail-closed safety, authority, privacy, migrations, rate/concurrency,
    provider governance, retention and recovery.
16. Minimal contributor/security guidance must be useful, not invented
    organizational machinery or addresses. No public issue should contain
    tokens, private conversations, complete `.env`, or sensitive exploit data.

### Doctor, distribution and proof

17. Add offline/static doctor tooling only for non-duplicative value. Default
    checks must not call Telegram/providers, change Docker resources/webhooks,
    migrate a database or require production access. Docker-only onboarding
    must not hide a host-Python/UV requirement.
18. Doctor exit zero means the selected phase is statically ready; missing
    required inputs produce actionable nonzero output with no secret values.
    Warnings never claim bot readiness. Disabled optionals do not block.
    Hermetic tests cover missing config, placeholders, polling without HTTPS,
    incomplete webhook/Qdrant/provider configuration and secret leakage.
19. A bounded self-host validator should cover the new distribution contract
    without duplicating product suites. It must be deterministic, offline,
    VCS-free/PATH-UV compatible and executable from Git materialization.
20. Prove fresh isolated Compose startup/base-to-head/core workers/health,
    synthetic polling cursor-to-outbound and optional webhook
    secret/idempotency/delivery, without real credentials or external calls.
21. Materialize the exact intended candidate Git tree, including new files
    and executable modes. Prove shallow checkout and VCS-free exports without
    `.git`, non-example env, credentials or developer virtualenv. Direct
    scripts must be `100755` in worktree, candidate index and candidate tree.
22. All 24 existing direct Quality validators, current supplemental and new
    gates, exact inline CI, static/Harness/shell/diff checks must exit zero.
    Reliability: zero failures. Eval: 130 total / 125 PASS / 5
    NOT_EVALUATED / 0 FAIL / 0 ERROR, with zero new product scenarios.
    No skip/xfail, masking, reduced selectors or weakened contracts.

## License and release boundary

Audit found no explicit project LICENSE/COPYING or pyproject license
declaration. Status: OWNER DECISION REQUIRED — OPEN-SOURCE LICENSE.
Do not select MIT/Apache/GPL automatically. Public source visibility is not
an open-source license grant. Technical self-host work may proceed, but final
public distribution claims must retain this unresolved decision.

No remote tags or CHANGELOG were observed. Until a maintainer establishes
releases, exact commit SHA is the durable identity. Future release notes should
record version/tag, source SHA, migration head, compatibility/config changes,
Quality result and known limitations. This task creates/pushes no tag.

## Dependencies, risks and recovery

Existing tenant/control/provider contracts, worker entrypoints and schema are
the implementation boundary. If self-host setup needs a new product/architecture
contract or migration, stop and report
`BLOCKED — SELF-HOST DISTRIBUTION REQUIRES PRODUCT/ARCHITECTURE CHANGE`.
The missing license does not block technical validation.

Changes are operational composition, configuration presentation, bounded
tooling/tests and documentation. Recover by reverting only this candidate's
identified changes or stopping only its owned synthetic project; never discard
user changes, downgrade real data or clean unrelated Docker resources.

## Deliverables and acceptance

Required: this reviewed Product Spec; design handoff; canonical deployment
policy; quickstart, VPS, upgrade/backup/restore and troubleshooting guidance;
current README/backend/docs/product/architecture/example navigation; warranted
doctor/validator and tests; completed execution plan and final audit handoff.

The original 77 phases and 56 mandatory gates remain binding in full. Final
audit must identify executable or observable evidence for every one, not just
the grouped requirements above. No Critical/High finding may remain. Allowed
final status is approved candidate/independent audit pending, owner license
decision required, requires fixes, or the specific product/architecture block;
never `COMPLETE`.

No commit, push, SPEC-044, public deployment, DNS/webhook mutation, live
Telegram/provider/TTS call, real restore, or new product work is authorized.
Next after verification: independent OpenCode self-host distribution audit.
