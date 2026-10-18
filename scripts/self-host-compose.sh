#!/usr/bin/env bash
# Explicit Compose operations using one private raw config, without shell eval.
set +x
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$root/scripts/lib/self-host-env.sh"
config="$root/.env.self-host"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  printf '%s\n' \
    'Usage: self-host-compose.sh [--config FILE] COMPOSE_ARGUMENTS...' \
    'Uses compose.self-host.yaml and one private raw file; never source that file.' \
    'Remaining arguments are explicit Docker Compose operations (may start live I/O).' \
    'Example: self-host-compose.sh --profile tools build setup-tool'
  exit 0
fi
if [[ "${1:-}" == --config ]]; then
  [[ $# -ge 3 && -n "$2" ]] || { self_host_error 'Missing configuration or Compose arguments.'; exit 1; }
  config="$2"
  shift 2
fi
[[ $# -gt 0 ]] || { self_host_error 'Provide an explicit Compose operation; see --help.'; exit 1; }
arguments=("$@")
operation=''
for ((index=0; index<${#arguments[@]}; index++)); do
  case "${arguments[$index]}" in
    -f|--file|-p|--project-name|--profile|--project-directory|--env-file|--ansi|--parallel|--progress)
      index=$((index + 1)) ;;
    -*) ;;
    *) operation="${arguments[$index]}"; break ;;
  esac
done
if [[ "$operation" == config ]]; then
  safe_selector=0
  for argument in "${arguments[@]}"; do
    case "$argument" in
      --environment|--environment=*|--variables|--variables=*|-o|--output|--output=*|--lock-image-digests)
        self_host_error 'Configuration dumps can expose secrets; use config --quiet or a safe metadata selector.'
        exit 1 ;;
      --quiet|-q|--services|--profiles|--volumes|--networks|--images)
        safe_selector=1 ;;
    esac
  done
  [[ "$safe_selector" == 1 ]] || {
    self_host_error 'Configuration dumps can expose secrets; use config --quiet or a safe metadata selector.'
    exit 1
  }
fi
self_host_read_config "$root" "$config"
command -v docker >/dev/null 2>&1 || { self_host_error 'Install Docker Engine/CLI for this Compose path.'; exit 1; }
self_host_compose "$@"
