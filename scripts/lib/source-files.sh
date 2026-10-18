#!/usr/bin/env bash
# Shared clean-copy inventory; Git history and local tooling are not required.
source_file_list() {
  local source_root="$1"
  local source_uv="$2"
  (
    cd "$source_root"
    # A VCS-free export may live beneath an unrelated ancestor Git worktree.
    # Only use an index owned by this source root, never the ancestor's index.
    if command -v git >/dev/null 2>&1 && [[ "$(git rev-parse --show-toplevel 2>/dev/null)" == "$(pwd -P)" ]]; then
      git ls-files --cached --others --exclude-standard -z
    else
      "$source_uv" run --locked python "$source_root/scripts/lib/source-files.py"
    fi
  )
}
