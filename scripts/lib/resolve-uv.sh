#!/usr/bin/env bash

# Resolve uv without requiring a project-local binary to be on PATH.
resolve_uv() {
  local project_root="$1"
  local local_uv="$project_root/.tools/uv"

  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi

  if [[ -x "$local_uv" ]]; then
    printf '%s\n' "$local_uv"
    return 0
  fi

  printf '%s\n' \
    "uv is required. Install it from https://docs.astral.sh/uv/ or add an executable at .tools/uv." \
    >&2
  return 127
}
