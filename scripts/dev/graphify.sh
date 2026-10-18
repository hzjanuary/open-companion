#!/usr/bin/env bash
# Optional maintainer navigation. Never invoked by application startup or CI.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
pin='graphifyy==0.9.74'
cd "$root"

usage() {
  printf '%s\n' 'Usage: scripts/dev/graphify.sh {build|update|query QUESTION|path FROM TO|explain NODE|status|version}' >&2
  exit 2
}
[[ $# -ge 1 ]] || usage
action="$1"
shift
case "$action" in
  version)
    [[ $# -eq 0 ]] || usage
    printf '%s\n' "$pin (selected pin; no package installation check)"
    exit 0
    ;;
  status)
    [[ $# -eq 0 ]] || usage
    if [[ -f graphify-out/graph.json && ! -L graphify-out && ! -L graphify-out/graph.json ]]; then
      printf '%s\n' 'Local derived graph present; freshness unknown. Verify relevant source; update after meaningful changes.'
    else
      printf '%s\n' 'No usable local graph. Optional: scripts/dev/graphify.sh build'
    fi
    exit 0
    ;;
  build|update)
    [[ $# -eq 0 ]] || usage
    args=(extract . --code-only)
    ;;
  query|explain)
    [[ $# -eq 1 && -n "$1" && "$1" != -* ]] || usage
    args=("$action" "$1" --graph graphify-out/graph.json)
    ;;
  path)
    [[ $# -eq 2 && -n "$1" && -n "$2" && "$1" != -* && "$2" != -* ]] || usage
    args=(path "$1" "$2" --graph graphify-out/graph.json)
    ;;
  *) usage ;;
esac

if [[ -L graphify-out || -L graphify-out/graph.json ]]; then
  printf '%s\n' 'Refusing symlinked graph output; use a local graphify-out directory.' >&2
  exit 2
fi
if [[ "$action" == query || "$action" == path || "$action" == explain ]]; then
  if [[ ! -f graphify-out/graph.json ]]; then
    printf '%s\n' 'No graphify-out/graph.json. Run scripts/dev/graphify.sh build first (optional, local code-only extraction).' >&2
    exit 2
  fi
fi
source "$root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$root")"
# A clean child environment prevents inherited keys/Graphify options from
# widening this fixed interface. HOME is preserved only for uv's normal cache.
# Package resolution may download tooling; extraction/query uses local code.
exec env -i PATH="$PATH" HOME="$HOME" LANG=C.UTF-8 \
  UV_OFFLINE="${UV_OFFLINE:-0}" \
  GRAPHIFY_OUT=graphify-out GRAPHIFY_NO_AUTO_REFRESH=1 \
  GRAPHIFY_QUERY_LOG_DISABLE=1 GRAPHIFY_NO_TIPS=1 \
  "$uv_bin" tool run --from "$pin" graphify "${args[@]}"
