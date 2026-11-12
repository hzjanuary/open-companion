"""Offline public source contract; not a secret audit or publication tool."""

import argparse
import hashlib
import json
import re
import stat
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
# Standard MIT text, independently reviewed against OSI; only owner/year filled.
LICENSE_SHA256 = "4d7986336b20626e0f4b37bdcd8010f718856bdf0fecb11f40dfdd5f705d49e1"
PUBLIC_DOCS = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "backend/README.md",
    "docs/README.md",
    "docs/product/README.md",
    "docs/product/self-hosted-deployment-profile.md",
    "docs/runbooks/self-hosted-quickstart.md",
    "docs/runbooks/self-hosted-vps.md",
    "docs/runbooks/self-hosted-upgrades.md",
    "docs/runbooks/self-hosted-troubleshooting.md",
    "docs/maintainers/release-process.md",
    "docs/maintainers/github-release-checklist.md",
    "docs/maintainers/release-notes-template.md",
    "docs/maintainers/dependency-licenses.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/pull_request_template.md",
)
SOURCE_FILES = (
    "LICENSE",
    "NOTICE",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    ".dockerignore",
    ".gitignore",
    ".env.example",
    ".env.self-host.example",
    "compose.yaml",
    "compose.self-host.yaml",
    "alembic.ini",
    "alembic/env.py",
    "backend/app/main.py",
    "scripts/lib/resolve-uv.sh",
    "scripts/lib/self-host-env.sh",
    "scripts/self_host/setup_operator.py",
    "scripts/self_host/runtime.py",
    "scripts/self_host/self_host_config.py",
    "scripts/self_host/validate_distribution.py",
    "docs/examples/self-host-provider-policy.json",
    ".github/workflows/ci.yml",
    "scripts/public_release/validate.py",
    "backend/tests/test_public_release.py",
)
USER_SCRIPTS = (
    "scripts/self-host-compose.sh",
    "scripts/self-host-doctor.sh",
    "scripts/validate-self-hosted.sh",
    "scripts/validate-production-readiness.sh",
    "scripts/production-config-fingerprint.sh",
    "scripts/validate-public-release.sh",
)
STALE_LICENSE = re.compile(
    r"OWNER DECISION REQUIRED\s*[—-]\s*OPEN.SOURCE LICENSE|"
    r"license (?:pending|undecided)|no project license (?:has been|is) granted|"
    r"source-visible only",
    re.I,
)
RETIRED_NAME = re.compile(r"lumi", re.I)
BRAND_DOCS = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/product/compliance-posture.md",
    "docs/product/encryption-ownership.md",
    "docs/product/data-governance.md",
    "docs/runbooks/ai-evaluations.md",
)
README_SECTIONS = (
    "What is January?",
    "Quick Start",
    "Features",
    "Architecture",
    "Supported AI providers",
    "Self-hosting",
    "Documentation",
    "Development",
    "Contributing",
    "Security",
    "Optional maintainer tooling",
    "License",
)


def heading_anchors(content: str) -> set[str]:
    """GitHub-style anchors for ordinary Markdown headings, excluding fences."""
    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    fence: str | None = None
    for line in content.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            character = marker[1][0]
            fence = (
                None if fence == character else character if fence is None else fence
            )
            continue
        if fence is not None:
            continue
        heading = re.match(r"^#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        if heading is None:
            continue
        text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", heading[1]).lower()
        slug = "".join(
            character for character in text if character.isalnum() or character in "-_ "
        ).replace(" ", "-")
        occurrence = occurrences.get(slug, 0)
        occurrences[slug] = occurrence + 1
        anchors.add(f"{slug}-{occurrence}" if occurrence else slug)
    return anchors


def validate_brand(root: Path) -> None:
    """Current identity and landing-page structure; historical paths excluded."""
    readme = (root / "README.md").read_text()
    lines = readme.splitlines()
    require(bool(lines) and lines[0] == "# January", "README title must be January")
    sections = re.findall(r"^## (.+)$", readme, re.M)
    require(
        all(sections.count(section) == 1 for section in README_SECTIONS),
        "README required sections missing or duplicated",
    )
    require(
        sections.index("Quick Start") <= 1
        and sections.index("Quick Start") < sections.index("Features"),
        "README Quick Start must precede feature detail",
    )
    require(
        len(readme.splitlines()) <= 400, "README must remain a bounded landing page"
    )
    require(
        re.search(
            r"SPEC-|\bcandidate\b|under validation|development complete|"
            r"remote CI pending",
            readme,
            re.I,
        )
        is None,
        "README contains internal development status jargon",
    )
    for relative in BRAND_DOCS:
        require(
            not RETIRED_NAME.search((root / relative).read_text()),
            f"Retired current product identity: {relative}",
        )
    # The current product contract intentionally preserves exactly one explicit
    # historical metadata line. Dated specs/ADRs/handoffs are not brand rewrites.
    contract = (root / "docs/product/SPEC.md").read_text()
    history = (
        "**Historical working name:** Lumi (retired; retained here as naming history)."
    )
    require("**Current name:** January\n" in contract, "Current product name missing")
    require(contract.count(history) == 1, "Explicit naming history must be preserved")
    require(
        not RETIRED_NAME.search(contract.replace(history, "", 1)),
        "Retired current product identity in current product contract",
    )
    require(
        not RETIRED_NAME.search(
            (root / "backend/app/application/commands.py").read_text()
        ),
        "Retired identity in product-owned command copy",
    )
    for target in ("LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md"):
        require(f"]({target})" in readme, f"README required public link: {target}")
    for target in re.findall(r"\]\(([^)\s]+)\)", readme):
        parsed = urlsplit(target.strip("<>"))
        if parsed.scheme or parsed.netloc:
            continue
        destination = (
            (root / unquote(parsed.path)).resolve()
            if parsed.path
            else root / "README.md"
        )
        require(
            destination.is_relative_to(root.resolve()) and destination.is_file(),
            "README link must resolve to an in-source file",
        )
        if parsed.fragment:
            require(
                destination.suffix == ".md"
                and unquote(parsed.fragment)
                in heading_anchors(destination.read_text()),
                "README heading anchor does not resolve",
            )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def direct_scripts(root: Path) -> set[str]:
    workflow = (root / ".github/workflows/ci.yml").read_text()
    return set(re.findall(r"\./(scripts/[\w-]+\.sh)\b", workflow)) | set(USER_SCRIPTS)


def validate_dependency_inventory(root: Path) -> None:
    """Reject stale or incomplete lock inventories; no network or legal verdict."""
    lock_bytes = (root / "uv.lock").read_bytes()
    packages = tomllib.loads(lock_bytes.decode())["package"]
    expected = {
        (package["name"], package["version"])
        for package in packages
        if package["name"] != "january"
    }
    inventory = json.loads(
        (root / "docs/validation/OSS-001-python-licenses.json").read_text()
    )
    require(
        inventory["uv_lock_sha256"] == hashlib.sha256(lock_bytes).hexdigest(),
        "Dependency license inventory must match the exact lock",
    )
    components = inventory["components"]
    require(
        len(components) == len(expected)
        and {(row["name"], row["version"]) for row in components} == expected,
        "Dependency license inventory must cover every locked third-party package",
    )
    require(
        all(
            row.get("license_expression")
            or row.get("license_metadata")
            or row.get("license_classifiers")
            for row in components
        ),
        "Missing dependency license metadata requires review",
    )
    sbom = json.loads(
        (root / "docs/validation/OSS-001-python-sbom.cdx.json").read_text()
    )
    require(
        sbom["bomFormat"] == "CycloneDX"
        and len(sbom["components"]) == len(expected)
        and {(row["name"], row["version"]) for row in sbom["components"]} == expected,
        "Dependency SBOM must cover the exact locked third-party packages",
    )


def validate(root: Path) -> None:
    root = root.resolve()
    validate_dependency_inventory(root)
    for relative in PUBLIC_DOCS + SOURCE_FILES:
        path = root / relative
        require(
            path.is_file() and not path.is_symlink(),
            f"Missing regular source: {relative}",
        )
    license_bytes = (root / "LICENSE").read_bytes()
    require(
        hashlib.sha256(license_bytes).hexdigest() == LICENSE_SHA256,
        "LICENSE must retain the reviewed standard MIT text and copyright",
    )
    metadata = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    require(
        metadata.get("license") == {"file": "LICENSE"},
        "Project license must reference LICENSE",
    )
    require(
        not any(
            "License ::" in c and "MIT" not in c
            for c in metadata.get("classifiers", [])
        ),
        "Conflicting license classifier",
    )
    readme = (root / "README.md").read_text()
    validate_brand(root)
    require(
        "planned public repository" not in readme.lower()
        and "once the owner publishes the repository" not in readme.lower(),
        "README must describe the existing public repository",
    )
    require(
        "## License\n\nLicensed under the [MIT License](LICENSE)" in readme,
        "README must declare and link MIT",
    )
    require(
        "[CONTRIBUTING.md](CONTRIBUTING.md)" in readme,
        "README contribution entrypoint missing",
    )
    require(
        "Copyright (c) 2025 Hoang Nguyen" in (root / "NOTICE").read_text(),
        "Installed Harness copyright notice missing",
    )
    for relative in PUBLIC_DOCS:
        path = root / relative
        content = path.read_text()
        require(
            not STALE_LICENSE.search(content),
            f"Stale current license claim: {relative}",
        )
        require(not path.stat().st_mode & 0o111, f"Document is executable: {relative}")
        for target in re.findall(r"\]\(([^)\s]+)\)", content):
            parsed = urlsplit(target.strip("<>"))
            if parsed.scheme or parsed.netloc:
                continue
            destination = (
                (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            )
            require(
                destination.is_relative_to(root.resolve()) and destination.exists(),
                f"Broken or outside-source local link: {relative}",
            )
    require(not (root / "LICENSE").stat().st_mode & 0o111, "LICENSE is executable")
    require(not (root / "NOTICE").stat().st_mode & 0o111, "NOTICE is executable")
    for relative in direct_scripts(root):
        path = root / relative
        require(
            path.is_file() and not path.is_symlink(),
            f"Missing direct script: {relative}",
        )
        mode = stat.S_IMODE(path.stat().st_mode)
        require(
            mode & 0o111 == 0o111 and not mode & 0o7000,
            f"Direct script lacks ordinary executable mode: {relative}",
        )
        require(
            path.read_bytes().startswith(b"#!/usr/bin/env bash\n")
            and b"\r" not in path.read_bytes(),
            f"Script requires Bash/LF: {relative}",
        )
    require(
        bool(tuple((root / "alembic/versions").glob("*.py"))),
        "Source migrations missing",
    )
    process = (root / "docs/maintainers/release-process.md").read_text()
    require(
        "FIRST PUBLIC VERSION: v0.1.0 — OWNER APPROVED; NOT YET PUBLISHED." in process,
        "Approved first-version and unpublished state missing",
    )
    require(metadata.get("version") == "0.1.0", "Approved package version mismatch")
    require(
        "## v0.1.0 — NOT YET PUBLISHED\n" in (root / "CHANGELOG.md").read_text(),
        "Approved unpublished changelog version missing",
    )
    require(
        "https://github.com/hzjanuary/open-companion" in readme,
        "Public repository location missing",
    )
    require(
        "## Unreleased\n" in (root / "CHANGELOG.md").read_text(),
        "Unreleased changelog missing",
    )
    require(
        "LICENSE NOTICE" in (root / "Dockerfile").read_text(),
        "Image license material missing",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        validate(args.root)
    except (ValueError, OSError, KeyError, TypeError) as error:
        # Only closed rule/path messages; never echo malformed file contents.
        if isinstance(
            error,
            OSError
            | KeyError
            | TypeError
            | tomllib.TOMLDecodeError
            | json.JSONDecodeError,
        ):
            print(
                "Public release validation failed: unreadable or malformed source",
                file=sys.stderr,
            )
        else:
            print(f"Public release validation failed: {error}", file=sys.stderr)
        return 1
    print("Public source license/metadata/docs/materialized-mode contract passed.")
    print(
        "Git-tree modes, archive completeness, secret review and full Quality "
        "are separate gates."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
