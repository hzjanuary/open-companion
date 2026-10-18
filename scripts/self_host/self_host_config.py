"""Small, non-executing raw env-file reader/writer for local operator tooling."""

import os
import re
import tempfile
from pathlib import Path


class SetupError(ValueError):
    """Actionable error whose message contains no configuration values."""


def read_config(path: Path, *, private: bool = True) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise SetupError("Configuration must be an existing regular file, not a link.")
    if private and os.name == "posix" and path.stat().st_mode & 0o077:
        raise SetupError("Restrict the configuration file to owner access (chmod 600).")
    if path.stat().st_size > 65_536:
        raise SetupError("Configuration exceeds the bounded file size.")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"JANUARY_[A-Z0-9_]+", key):
            raise SetupError(
                "Use raw JANUARY_NAME=value assignments; never shell code."
            )
        if key in values:
            raise SetupError("Duplicate configuration assignment.")
        if value != value.strip() or value.startswith(("'", '"')):
            raise SetupError("Raw values must be unquoted, without surrounding spaces.")
        values[key] = value
    return values


def require_local_target(path: Path) -> None:
    """Writable names must match this repository's actual secret ignore rules."""
    if path.name not in {".env.self-host", ".env.local"} and not (
        path.name.startswith(".env.") and path.name.endswith(".local")
    ):
        raise SetupError("Write only ignored local configuration, never an example.")


def update_config(path: Path, updates: dict[str, str]) -> None:
    """Atomically replace only selected fields, preserving comments and others."""
    require_local_target(path)
    read_config(path, private=False)
    original = path.read_text(encoding="utf-8")
    pending = dict(updates)
    lines = []
    for line in original.splitlines():
        key = line.partition("=")[0]
        lines.append(f"{key}={pending.pop(key)}" if key in pending else line)
    lines.extend(f"{key}={value}" for key, value in pending.items())
    descriptor, temporary = tempfile.mkstemp(prefix=".self-host-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or path.read_text(encoding="utf-8") != original:
            raise SetupError("Configuration changed during setup; stop and review.")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
