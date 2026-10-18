"""NUL-separated VCS-free source inventory for the AI-eval clean-copy proof.

Simple repository ignore rules are applied without Git. Unsupported negation
fails closed instead of inventing an incomplete source archive.
"""

import fnmatch
import os
import sys
from pathlib import Path


def source_files(root: Path) -> list[str]:
    rules = [
        line.strip()
        for line in (root / ".gitignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if any(rule.startswith("!") or "\\" in rule for rule in rules):
        raise ValueError("unsupported export ignore syntax")
    rules += [".git/", "graphify-out/"]
    public_env_templates = {
        ".env.example",
        ".env.demo.example",
        ".env.self-host.example",
        ".env.zalo-verification.example",
    }

    def ignored(path: Path, directory: bool) -> bool:
        relative = path.relative_to(root).as_posix()
        if path.name.startswith(".env") and relative not in public_env_templates:
            return True
        for rule in rules:
            if rule.endswith("/") and not directory:
                continue
            pattern = rule.rstrip("/")
            if pattern.startswith("/"):
                if fnmatch.fnmatchcase(relative, pattern[1:]):
                    return True
            elif "/" in pattern:
                if fnmatch.fnmatchcase(relative, pattern):
                    return True
            elif fnmatch.fnmatchcase(path.name, pattern):
                return True
        return False

    files = []
    for current, dirs, names in os.walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if not ignored(base / d, True))
        for name in sorted(names):
            path = base / name
            if not ignored(path, False):
                if not path.is_file() or path.is_symlink():
                    raise ValueError("export source must contain regular files")
                files.append(path.relative_to(root).as_posix())
    return sorted(files)


if __name__ == "__main__":
    try:
        for relative in source_files(Path.cwd()):
            sys.stdout.buffer.write(os.fsencode(relative) + b"\0")
    except (OSError, ValueError):
        sys.exit("VCS-free source inventory failed (details redacted)")
