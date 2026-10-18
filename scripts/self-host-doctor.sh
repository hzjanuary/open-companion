#!/usr/bin/env bash
# Bounded distribution preflight, not a provider/bot/dependency readiness probe.
set +x
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/self-host-env.sh"
config="$root/.env.self-host"
policy="$root/.local/self-host/provider-policy.json"
profile=polling
phase=runtime
typed=0
optional_profiles=()

usage() {
  printf '%s\n' \
    'Usage: self-host-doctor.sh [--offline] [--config FILE] [--policy FILE]' \
    '       [--profile polling|webhook] [--phase template|setup|runtime]' \
    '       [--enable qdrant|summaries|semantic-memory|knowledge-rag|scheduling]' \
    '       [--typed]' \
    'Default: static/offline; no host Python/uv, daemon check or resource writes.' \
    '--typed: explicitly creates/removes one non-root, network-disabled container' \
    '         from an already built local image; never pulls/builds/migrates.' \
    'Exit 0: selected offline checks pass, NOT a live/persisted readiness claim.' \
    'Nonzero: actionable blocker. No Telegram/provider calls or secret output.'
}

fail() {
  printf 'Self-host preflight blocked: %s\n' "$1" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline) shift ;;
    --typed) typed=1; shift ;;
    --help|-h) usage; exit 0 ;;
    --config|--policy|--profile|--phase|--enable)
      [[ $# -ge 2 && -n "$2" ]] || fail 'An option value is missing; see --help.'
      case "$1" in
        --config) config="$2" ;;
        --policy) policy="$2" ;;
        --profile) profile="$2" ;;
        --phase) phase="$2" ;;
        --enable) optional_profiles+=("$2") ;;
      esac
      shift 2 ;;
    *) fail 'Unknown option; see --help.' ;;
  esac
done
case "$profile" in polling|webhook) ;; *) fail 'Choose polling or webhook.' ;; esac
case "$phase" in template|setup|runtime) ;; *) fail 'Choose template, setup or runtime.' ;; esac
[[ "$phase" != template || "$typed" == 0 ]] || fail 'Typed checks need setup/runtime inputs.'
for selected in ${optional_profiles[@]+"${optional_profiles[@]}"}; do
  case "$selected" in
    qdrant|summaries|semantic-memory|knowledge-rag|scheduling) ;;
    *) fail 'Unknown optional profile; see --help.' ;;
  esac
done

self_host_read_config "$root" "$config"
config="$self_host_config"
get_value() { self_host_value "$1"; }

required() {
  local candidate normalized
  candidate="$(get_value "$1")"
  [[ -n "$candidate" ]] || fail "$1 is required for the selected phase."
  normalized="$(printf '%s' "$candidate" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    *change-me*|*changeme*|*placeholder*|*example.invalid*|*synthetic*|*test-only*|*fake-*|*dummy*|january-local|your_*|replace_*)
      fail "$1 contains an obvious placeholder." ;;
  esac
}

bool_value() {
  local candidate
  candidate="$(get_value "$1")"
  case "$candidate" in
    true|false) printf '%s' "$candidate" ;;
    '') printf 'false' ;;
    *) fail 'Feature flags must use the canonical raw true/false spelling.' ;;
  esac
}

has_profile() {
  local candidate
  for candidate in ${optional_profiles[@]+"${optional_profiles[@]}"}; do
    [[ "$candidate" != "$1" ]] || return 0
  done
  return 1
}

feature_pair() {
  local feature worker
  feature="$(bool_value "$1")"
  worker="$(bool_value "$2")"
  [[ "$feature" == "$worker" ]] || fail "$1 and $2 must be enabled/disabled together."
  if [[ "$feature" == true ]]; then
    has_profile "$3" || fail "Enabled $1 requires its matching Compose profile."
  elif has_profile "$3"; then
    fail "Selected optional profile requires $1 and $2."
  fi
}

reachable_container_url() {
  local address
  address="$(get_value JANUARY_LLM_OLLAMA_BASE_URL)"
  case "$address" in
    http://*|https://*) ;;
    *) fail 'Configure an absolute Ollama HTTP(S) address reachable from the container.' ;;
  esac
  case "$address" in
    *://127.*|*://localhost*|*://\[::1\]*)
      fail 'Container-local Ollama loopback is not the host; choose a bounded reachable address.' ;;
  esac
}

provider_checks() {
  local prefix
  case "$1" in
    openai|gemini|groq|openrouter)
      prefix="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
      required "JANUARY_LLM_${prefix}_MODEL"
      required "JANUARY_LLM_${prefix}_API_KEY" ;;
    ollama) required JANUARY_LLM_OLLAMA_MODEL; reachable_container_url ;;
    *) fail 'Select an actual supported LLM provider.' ;;
  esac
}

if [[ "$phase" != template ]]; then
  for name in JANUARY_DATABASE_NAME JANUARY_DATABASE_USER JANUARY_DATABASE_PASSWORD \
    JANUARY_CONTROL_PLANE_JWT_SECRET JANUARY_CONTROL_PLANE_JWT_ISSUER \
    JANUARY_CONTROL_PLANE_JWT_AUDIENCE JANUARY_TELEGRAM_BOT_TOKEN; do
    required "$name"
  done
  jwt_secret="$(get_value JANUARY_CONTROL_PLANE_JWT_SECRET)"
  [[ "${#jwt_secret}" -ge 32 ]] || fail 'The local JWT secret must contain at least 32 characters.'
  for name in JANUARY_TELEGRAM_ENABLED JANUARY_LLM_ENABLED \
    JANUARY_COMMAND_WORKER_ENABLED JANUARY_OUTBOUND_DELIVERY_ENABLED; do
    [[ "$(bool_value "$name")" == true ]] || fail "$name is required for supported guarded text chat."
  done
  [[ "$(get_value JANUARY_TELEGRAM_DELIVERY_MODE)" == "$profile" ]] || fail 'Chosen profile and configured Telegram delivery mode differ.'
  provider="$(get_value JANUARY_LLM_PRIMARY_PROVIDER)"
  provider_checks "$provider"
  fallback="$(get_value JANUARY_LLM_FALLBACK_PROVIDER)"
  if [[ -n "$fallback" ]]; then
    [[ "$fallback" != "$provider" ]] || fail 'Fallback provider must differ from the primary provider.'
    provider_checks "$fallback"
  fi
  if [[ "$profile" == webhook ]]; then
    required JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL
    required JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN
    webhook_url="$(get_value JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL)"
    [[ "$webhook_url" =~ ^https://[^/[:space:]]+ ]] || fail 'Webhook requires an absolute public HTTPS base URL and valid TLS.'
  fi
  if [[ "$phase" == runtime ]]; then
    for name in JANUARY_TELEGRAM_TENANT_ID JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID; do
      required "$name"
      identifier="$(get_value "$name")"
      [[ "$identifier" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || fail "$name must be a canonical UUID."
    done
    [[ "$(get_value JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS)" == '[]' ]] || fail 'Complete authenticated setup and clear initial bootstrap subjects before runtime.'
  fi
  feature_pair JANUARY_CONVERSATION_SUMMARIES_ENABLED JANUARY_SUMMARY_WORKER_ENABLED summaries
  feature_pair JANUARY_SEMANTIC_MEMORY_ENABLED JANUARY_SEMANTIC_MEMORY_WORKER_ENABLED semantic-memory
  feature_pair JANUARY_KNOWLEDGE_RAG_ENABLED JANUARY_KNOWLEDGE_INDEX_WORKER_ENABLED knowledge-rag
  feature_pair JANUARY_PROACTIVE_SCHEDULING_ENABLED JANUARY_SCHEDULER_WORKER_ENABLED scheduling
  semantic_enabled="$(bool_value JANUARY_SEMANTIC_MEMORY_ENABLED)"
  knowledge_enabled="$(bool_value JANUARY_KNOWLEDGE_RAG_ENABLED)"
  tts_enabled="$(bool_value JANUARY_TELEGRAM_VOICE_TTS_ENABLED)"
  if [[ "$semantic_enabled" == true || "$knowledge_enabled" == true ]]; then
    [[ "$(get_value JANUARY_EMBEDDING_PROVIDER)" == ollama ]] || fail 'Enabled vector features require the supported Ollama embedding provider.'
    required JANUARY_EMBEDDING_MODEL
    reachable_container_url
  fi
  if [[ "$tts_enabled" == true ]]; then
    required JANUARY_LLM_OPENAI_API_KEY
  fi
  [[ -f "$policy" && ! -L "$policy" && "$(wc -c < "$policy")" -le 65536 ]] || fail 'Provide the bounded operator policy JSON file, not a symlink.'
  policy="$(cd "$(dirname "$policy")" && pwd)/$(basename "$policy")"
  policy_content="$(<"$policy")"
  [[ ! "$policy_content" =~ (^|[^[:alnum:]_])null([^[:alnum:]_]|$) ]] || fail 'Fill all operator policy limits/prices; the example is intentionally incomplete.'
  [[ "$policy_content" =~ \"json_schema_supported\"[[:space:]]*:[[:space:]]*true ]] || fail 'Explicitly confirm the selected model JSON-schema contract.'
  if [[ "$provider" == ollama ]]; then
    [[ "$policy_content" =~ \"data_class\"[[:space:]]*:[[:space:]]*\"local\" ]] || fail 'Ollama policy must retain the local data boundary.'
  else
    [[ "$policy_content" =~ \"data_class\"[[:space:]]*:[[:space:]]*\"approved_external\" ]] || fail 'Explicitly affirm the hosted model approved-external data boundary.'
  fi
fi

# Static revision markers only; actual Alembic/head and database revision proof
# remain separate. This catches accidental additional heads without host Python.
head="$(awk -F '\"' '
  /^revision:/ { revisions[$2] = 1 }
  /^down_revision:/ && NF > 1 { parents[$2] = 1 }
  END { for (revision in revisions) if (!(revision in parents)) print revision }
' "$root"/alembic/versions/*.py)"
[[ "$head" == 0026_conversation_feedback ]] || fail 'Static migration markers must have the single expected 0026 head; no migration or database check performed.'

command -v docker >/dev/null 2>&1 || fail 'Install Docker Engine/CLI for this Compose path.'
docker compose version >/dev/null 2>&1 || fail 'Install the Docker Compose plugin (raw env_file support is required).'
compose_profiles=(--profile "$profile")
for selected in ${optional_profiles[@]+"${optional_profiles[@]}"}; do
  compose_profiles+=(--profile "$selected")
done
if ! self_host_compose "${compose_profiles[@]}" config --quiet >/dev/null 2>&1; then
  fail 'Compose cannot render the selected file/profiles; check raw env_file support, syntax and ports (values redacted).'
fi

if [[ "$typed" == 1 ]]; then
  [[ "$(id -u)" != 0 ]] || fail 'Run --typed as the normal self-host operator, not root.'
  image="$(get_value JANUARY_BACKEND_IMAGE)"
  image="${image:-january-self-host:checkout}"
  docker image inspect "$image" >/dev/null 2>&1 || fail 'Cannot inspect the selected local image; check Docker engine/access and the local build. No pull/build attempted.'
  if ! docker run --pull never --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$config,dst=/workspace/.env.self-host,readonly" \
    --mount "type=bind,src=$policy,dst=/workspace/provider-policy.json,readonly" \
    "$image" python /app/self-host/setup_operator.py check --phase "$phase" \
    --policy /workspace/provider-policy.json >/dev/null 2>&1; then
    fail 'Typed configuration/policy check failed; review actual Settings, policy types/limits and optional graph (values redacted).'
  fi
  printf 'PASS: offline typed %s/%s configuration and policy check.\n' "$profile" "$phase"
else
  printf 'PASS: offline static %s/%s checks only; typed Settings/policy NOT verified.\n' "$profile" "$phase"
fi
printf '%s\n' 'Not verified: persisted authority/policies, dependency/schema health, worker ownership, Telegram/model reachability or delivered messages.'
