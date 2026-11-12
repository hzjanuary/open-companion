# January v0.1.0 — Initial Self-hosted Telegram AI Companion Source Preview

**NOT YET PUBLISHED · Independent audit pending**

The owner approved v0.1.0. Publication date is not assigned. No tag,
GitHub Release or official prebuilt image is implied. The source repository is
already public; this proposed release remains unpublished.

## Highlights

January is a self-hosted Telegram companion backend with configurable
conversation/personality behavior, structured response plans and durable
processing. Telegram supports polling or guarded HTTPS webhook ingress, replies,
mentions, stickers, optional bounded image/audio understanding, regeneration,
lightweight reactions, explicit feedback, typing presence and reply-only voice
playback. Zalo remains frozen and unsupported.

## Self-hosting and providers

Build from source with Docker Compose for polling-first local operation or one
VPS. Configure credentials, authenticated tenant/assistant/connection authority,
model capabilities and explicit limits before enabling delivery. Webhooks need
an appropriate HTTPS endpoint and secret. No managed SaaS or official published
registry image is offered. Start with the
[self-host quickstart](../runbooks/self-hosted-quickstart.md).

Five implemented chat adapters are OpenAI, Gemini, Groq, OpenRouter and Ollama.
Routing/fallback, health, rate/concurrency and budget controls are available;
adapter support does not guarantee parity across models. Ollama needs a
separately operated model server. Optional transcription and OpenAI TTS depend
on the enabled provider configuration.

## Memory, context and knowledge

Explicit conversation memory has user inspection/edit/recall/delete controls.
Private chats support bounded creator-private personal context. Optional
short-lived summaries, semantic explicit-memory retrieval and operator-managed
knowledge/RAG are separate choices. PostgreSQL owns canonical state; optional
Qdrant is a derived index whose references are revalidated against PostgreSQL.

## Safety, privacy and operations

Fail-closed authority and tenant/conversation boundaries, structural safety,
export/erasure, bounded retention and content-safe telemetry are implemented.
External LLM/transcription/TTS providers receive required content for enabled
requests; Telegram remains external even with local Ollama. Self-hosting does
not guarantee local-only data, comprehensive moderation, regulatory compliance
or end-to-end encryption.

Durable leases, inbox/outbox deduplication and bounded recovery support workers.
Uncertain Telegram delivery is not blindly retried; exactly-once delivery is
not promised. Offline configuration checks, readiness, metrics, explicit
migrations and backup/restore guidance support operators. Review the
[upgrade and recovery guide](../runbooks/self-hosted-upgrades.md) before upgrades.

## Migration and limitations

This publication preparation adds no product feature or migration. The sole
Alembic head remains `0026_conversation_feedback`; current locked validation
uses Python 3.12, PostgreSQL 16, Redis 7 and optional Qdrant v1.13.4. Interfaces
and configuration can evolve. No LTS, managed backup, blanket privacy/security
guarantee or guaranteed rollback/downgrade is offered. Community support is
best-effort. Synthetic Quality does not prove live bot/model availability.

## License and publication gates

Source is [MIT licensed](../../LICENSE); retain [third-party notices](../../NOTICE).
Report vulnerabilities through [SECURITY.md](../../SECURITY.md).
Independent audit of the exact approved private package/source, refreshed
history/privacy review, exact-SHA GitHub Quality and owner authorization remain
required under the [current procedure](../maintainers/post-publication-source-release.md).
The private audit package location is pending; the public SPEC-048 handoff is
historical context, not independent approval.

## Distribution and source identity

The public repository is https://github.com/hzjanuary/open-companion. The
original root is `069642473d6a39824b7a5ccf9c844cb8e6c4f354`; OSS-001 began at
main `612f89c6724261873d38cfa9a9639eb5836cb41a`. Record final source SHA,
independent audit binding, exact-SHA Quality runs and source checksums in the
[acceptance ledger](../validation/OSS-001-acceptance.md) when observed.

Proposed distribution: GitHub **Pre-release**, GitHub-generated source ZIP and
tar.gz only. No official binary, package, prebuilt Docker image, model weights
or deployment. Source approval and local-image security approval are separate
owner decisions. Review the image findings before building for operation;
a source-only release never certifies the OS/container dependencies.

## Image security notice — owner decision pending

The local corrected-source Docker build was scanned separately using pinned
Trivy 0.76.1. It reports 45 HIGH OS package/advisory instances with no fixed
version in the observed DB, plus lower-severity OS and base-image pip findings.
No CRITICAL was reported. See the
[container inventory and complete finding metadata](../validation/OSS-001-container-inventory.json).
No official prebuilt image is published or approved. A source-only release
requires an explicit owner risk decision; source CI does not approve an image
or guarantee the security of later mutable-tag builds.

This preparation also corrects raw retention for stalled jobs and prevents
late edits from restoring redacted messages. It preserves all 26 migrations
and the separate explicit-memory lifecycle. Validation/audit status is tracked
in the acceptance ledger; no live bot/model result is implied.

## Source identity and upgrade

This first source release introduces no migration or configuration default change.
Existing operators must back up PostgreSQL and erasure records, review config and
compatibility, perform migration preflight with one migration owner, restart and
verify readiness/workers before deliberate smoke. There is no automated backup
or guaranteed database downgrade. Linux/Bash/POSIX permissions, Python 3.12,
PostgreSQL 16, Redis 7 and Compose raw env-file support are the documented path;
other platforms/major versions are not claimed validated.
