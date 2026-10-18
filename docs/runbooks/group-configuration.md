# Group Configuration

SPEC-009 exposes no Telegram commands and no HTTP mutation endpoint. Use the
explicit no-network runtime command against a local migrated database. From the
repository root, prefix the command with `PYTHONPATH=backend`; it contacts only
the configured local PostgreSQL database, never Telegram or an LLM provider.

```bash
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json seed-default \
  --assistant-id ASSISTANT_UUID --apply
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json list-profiles \
  --assistant-id ASSISTANT_UUID
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json list-versions \
  --profile-id PROFILE_UUID
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json show-current \
  --conversation-id CONVERSATION_UUID
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json show-effective \
  --conversation-id CONVERSATION_UUID
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json list-history \
  --conversation-id CONVERSATION_UUID
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json create-profile \
  --assistant-id ASSISTANT_UUID --slug calmer --display-name Calmer --apply
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json create-version \
  --profile-id PROFILE_UUID --humor-level 0.2 --teasing-level 0 --apply
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json set \
  --conversation-id CONVERSATION_UUID --expected-revision 1 \
  --profile-version-id PROFILE_VERSION_UUID --humor-level 0 --apply
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json pause \
  --conversation-id CONVERSATION_UUID --expected-revision 2 --apply
PYTHONPATH=backend uv run python -m app.runtime.group_configuration --json resume \
  --conversation-id CONVERSATION_UUID --response-mode mention_only \
  --expected-revision 3 --apply
```

Reads do not mutate. Every write requires `--apply`; a stale
`--expected-revision` fails instead of replacing another operator's revision.
`set` accepts typed response mode, sticker state, profile-version selection,
and the documented bounded overrides. Use `--clear-override FIELD` to return a
single override to its profile value. `archive-profile` and `set-default` are
also explicit `--apply` mutations. The command accepts no prompt text and does
not contact Telegram or a model provider. Profile versions and conversation
revisions are immutable; a changed configuration creates a new revision and
snapshots apply only to later jobs.
