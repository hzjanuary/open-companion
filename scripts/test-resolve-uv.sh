#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"

temp_dir="$(mktemp -d)"
trap '/bin/rm -rf "$temp_dir"' EXIT

mkdir -p "$temp_dir/empty" "$temp_dir/path" "$temp_dir/project/.tools"
path_uv="$temp_dir/path/uv"
local_uv="$temp_dir/project/.tools/uv"
touch "$path_uv" "$local_uv"
chmod +x "$path_uv" "$local_uv"

PATH="$temp_dir/path:$PATH"
[[ "$(resolve_uv "$temp_dir/project")" == "$path_uv" ]]

PATH="$temp_dir/empty"
[[ "$(resolve_uv "$temp_dir/project")" == "$local_uv" ]]

if resolve_uv "$temp_dir/missing" >"$temp_dir/output" 2>&1; then
  printf '%s\n' "expected resolve_uv to fail when uv is unavailable" >&2
  exit 1
fi
/usr/bin/grep -Fq "uv is required" "$temp_dir/output"
