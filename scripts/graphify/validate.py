"""Offline January integration checks, not Graphify internals or a secret audit."""

import argparse
import hashlib
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS_SHA256 = "395bb2e7e9a7c7da54dcf762a0823d20c32ffc50d5d0f3cc40e084021b88faf4"
PIN = "graphifyy==0.9.74"
IGNORE = (
    ".git/",
    ".env",
    ".env.*",
    ".venv/",
    ".tools/",
    ".runtime/",
    ".local/",
    "graphify-out/",
    "backups/",
    "*.dump",
    "*.pem",
    "*.key",
    "credentials/",
    "secrets/",
)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def validate(root: Path) -> None:
    wrapper_path = root / "scripts/dev/graphify.sh"
    wrapper = wrapper_path.read_text()
    require(f"pin='{PIN}'" in wrapper, "explicit audited version pin missing")
    require("set -euo pipefail" in wrapper, "wrapper must fail closed")
    require("args=(extract . --code-only)" in wrapper, "local code-only build missing")
    require("build|update)" in wrapper, "update must use the safe build branch")
    require("exec env -i" in wrapper, "clean child environment missing")
    for setting in (
        "GRAPHIFY_OUT=graphify-out",
        "GRAPHIFY_NO_AUTO_REFRESH=1",
        "GRAPHIFY_QUERY_LOG_DISABLE=1",
        "GRAPHIFY_NO_TIPS=1",
    ):
        require(setting in wrapper, f"required wrapper isolation: {setting}")
    require(
        not re.search(
            r"--(?:backend|dedup-llm|postgres|google-workspace|mode)\b", wrapper
        ),
        "wrapper must not expose semantic/provider/database options",
    )
    for relative in (
        "scripts/dev/graphify.sh",
        "scripts/validate-graphify-integration.sh",
    ):
        p = root / relative
        require(
            p.is_file() and not p.is_symlink(), f"regular script required: {relative}"
        )
        require(
            stat.S_IMODE(p.stat().st_mode) == 0o755,
            f"script mode must be 755: {relative}",
        )
        require(b"\r" not in p.read_bytes(), f"LF required: {relative}")
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    require(
        not any(re.match(r"graphify", dep, re.I) for dep in project["dependencies"]),
        "Graphify must not be an application dependency",
    )
    for relative in ("Dockerfile", "uv.lock", "compose.yaml", "compose.self-host.yaml"):
        require(
            "graphify" not in (root / relative).read_text().lower(),
            f"Graphify runtime/lock dependency: {relative}",
        )
    ignore = (root / ".gitignore").read_text().splitlines()
    require("graphify-out/" in ignore, "derived graph must be gitignored")
    # Read the index when available; ignored dirty/stale output is permitted.
    # VCS-free archives have no index: their contents are a separate export gate.
    git = shutil.which("git")
    if git and (root / ".git").exists():
        tracked = subprocess.run(
            [git, "-C", str(root), "ls-files", "-z", "--", "graphify-out"],
            capture_output=True,
            check=False,
        )
        require(tracked.returncode == 0, "cannot inspect generated graph index")
        require(not tracked.stdout, "generated graph must not be tracked/staged")
    require(
        "graphify-out" in (root / ".dockerignore").read_text().splitlines(),
        "derived graph must be excluded from Docker context",
    )
    rules = (root / ".graphifyignore").read_text().splitlines()
    for rule in IGNORE:
        require(rule in rules, f"Graphify sensitive-state exclusion missing: {rule}")
    for authority in (
        "backend/app",
        "alembic",
        "scripts",
        "docs",
        "tests",
        "backend/tests",
    ):
        require(
            authority not in rules and authority + "/" not in rules,
            f"authoritative source excluded: {authority}",
        )
    agents = (root / "AGENTS.md").read_bytes()
    begin, end = b"<!-- HARNESS:BEGIN -->", b"<!-- HARNESS:END -->"
    require(
        agents.count(begin) == agents.count(end) == 1,
        "Harness markers missing/duplicated",
    )
    a, b = agents.index(begin), agents.index(end) + len(end)
    require(
        hashlib.sha256(agents[a:b]).hexdigest() == HARNESS_SHA256,
        "authoritative Harness block changed",
    )
    require(
        "Contributors can work without Graphify."
        in (root / "CONTRIBUTING.md").read_text(),
        "Graphify must remain optional for contributors",
    )
    for p in (root / "docs/runbooks").glob("self-host*.md"):
        require(
            "graphify" not in p.read_text().lower(),
            "Graphify added to self-host requirements",
        )
    scripts = list((root / "scripts").glob("validate*.sh"))
    workflow = root / ".github/workflows/ci.yml"
    for p in scripts + [workflow]:
        code = "\n".join(
            line
            for line in p.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        code = code.replace(
            "bash -n scripts/dev/graphify.sh scripts/validate-graphify-integration.sh",
            "",
        )
        require(
            not re.search(
                r"\buvx\b.*graphify|\buv\b.*(?:tool|--from).*graphify|"
                r"\b(?:uv|pip|pipx)\b.*\bgraphifyy\b|"
                r"(?:^|[\s;])graphify(?:\s|$)|scripts/dev/graphify\.sh",
                code,
                re.M,
            ),
            f"canonical Graphify invocation/download: {p.relative_to(root)}",
        )
    for relative in (
        ".codex/skills/graphify",
        ".codex/hooks.json",
        ".opencode/skills/graphify",
        ".opencode/plugins/graphify.js",
    ):
        require(
            not (root / relative).exists(),
            f"unauthorized generated integration: {relative}",
        )
    guide = (root / "docs/maintainers/graphify.md").read_text()
    for contract in (PIN, "non-authoritative", "Apache-2.0", "semantic", "stale"):
        require(contract in guide, f"maintainer boundary missing: {contract}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        validate(args.root.resolve())
    except (OSError, ValueError, KeyError) as exc:
        # Do not echo raw file content or parser details that could contain keys.
        message = str(exc) if type(exc) is ValueError else "source contract unreadable"
        print(f"Graphify integration: FAIL: {message}", file=sys.stderr)
        return 1
    print("Graphify integration: PASS (offline source contract; no tool execution)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
