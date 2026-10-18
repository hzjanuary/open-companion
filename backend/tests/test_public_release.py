"""Public release contract and isolated VCS-free CLI mutation rejection."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/public_release/validate.py"
spec = importlib.util.spec_from_file_location("public_release", SCRIPT)
assert spec is not None and spec.loader is not None
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def candidate(tmp_path: Path) -> Path:
    # Copy sources, never ignored credentials or developer environments/history.
    for name in ("docs", "scripts", "backend", "alembic", ".github"):
        shutil.copytree(
            ROOT / name,
            tmp_path / name,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "bin", ".pytest_cache", ".mypy_cache"
            ),
        )
    for name in (
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CHANGELOG.md",
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
        "AGENTS.md",
    ):
        shutil.copy2(ROOT / name, tmp_path / name)
    # Current navigation also links the installed public skills.
    shutil.copytree(
        ROOT / ".agents",
        tmp_path / ".agents",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return tmp_path


def run(candidate: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(candidate / "scripts/public_release/validate.py")],
        cwd=candidate,
        env={"PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_actual_public_contract() -> None:
    release.validate(ROOT)


def test_vcs_free_cli_without_git_uv_or_credentials(candidate: Path) -> None:
    assert not (candidate / ".git").exists()
    assert not (candidate / ".env").exists()
    assert not (candidate / ".venv").exists()
    result = run(candidate)
    assert result.returncode == 0, result.stderr


def test_cli_accepts_relative_source_root(candidate: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(candidate / "scripts/public_release/validate.py"),
            "--root",
            ".",
        ],
        cwd=candidate,
        env={"PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "license_missing",
        "license_modified",
        "readme_apache",
        "contribution_link",
        "script_mode",
        "license_executable",
        "metadata",
        "stale_license",
        "source_missing",
        "notice_missing",
        "retired_title",
        "quick_start_missing",
        "license_link",
        "canonical_brand",
        "heading_anchor",
        "runtime_brand",
        "readme_phase_jargon",
        "package_version",
        "unpublished_version",
        "public_repository",
    ],
)
def test_isolated_mutations_fail_process(candidate: Path, mutation: str) -> None:
    if mutation == "license_missing":
        (candidate / "LICENSE").unlink()
    elif mutation == "license_modified":
        with (candidate / "LICENSE").open("a") as file:
            file.write("Additional restriction: no commercial use.\n")
    elif mutation == "readme_apache":
        path = candidate / "README.md"
        path.write_text(
            path.read_text().replace(
                "[MIT License](LICENSE)", "[Apache License](LICENSE)"
            )
        )
    elif mutation == "contribution_link":
        path = candidate / "CONTRIBUTING.md"
        path.write_text(
            path.read_text().replace("(SECURITY.md)", "(does-not-exist.md)")
        )
    elif mutation == "script_mode":
        (candidate / "scripts/self-host-compose.sh").chmod(0o644)
    elif mutation == "license_executable":
        (candidate / "LICENSE").chmod(0o755)
    elif mutation == "metadata":
        path = candidate / "pyproject.toml"
        path.write_text(
            path.read_text().replace('file = "LICENSE"', 'text = "Apache-2.0"')
        )
    elif mutation == "stale_license":
        with (candidate / "docs/runbooks/self-hosted-quickstart.md").open("a") as file:
            file.write("\nOWNER DECISION REQUIRED — OPEN-SOURCE LICENSE\n")
    elif mutation == "source_missing":
        (candidate / "scripts/self_host/setup_operator.py").unlink()
    elif mutation == "notice_missing":
        (candidate / "NOTICE").write_text("No notices.\n")
    elif mutation == "retired_title":
        path = candidate / "README.md"
        path.write_text(path.read_text().replace("# January\n", "# Lumi\n", 1))
    elif mutation == "quick_start_missing":
        path = candidate / "README.md"
        path.write_text(path.read_text().replace("## Quick Start\n", "## Setup\n"))
    elif mutation == "license_link":
        path = candidate / "README.md"
        path.write_text(path.read_text().replace("(LICENSE)", "(missing-license)"))
    elif mutation == "canonical_brand":
        path = candidate / "docs/product/data-governance.md"
        path.write_text(path.read_text().replace("January", "Lumi", 1))
    elif mutation == "heading_anchor":
        path = candidate / "README.md"
        path.write_text(
            path.read_text().replace("(#quick-start)", "(#missing-section)")
        )
    elif mutation == "runtime_brand":
        path = candidate / "backend/app/application/commands.py"
        path.write_text(
            path.read_text().replace("January is checking in", "Lumi is checking in")
        )
    elif mutation == "readme_phase_jargon":
        path = candidate / "README.md"
        path.write_text(path.read_text() + "\nSPEC-038 candidate under validation\n")
    elif mutation == "package_version":
        path = candidate / "pyproject.toml"
        path.write_text(
            path.read_text().replace('version = "0.1.0"', 'version = "0.2.0"')
        )
    elif mutation == "unpublished_version":
        path = candidate / "CHANGELOG.md"
        path.write_text(
            path.read_text().replace("## v0.1.0 — NOT YET PUBLISHED", "## v0.1.0")
        )
    elif mutation == "public_repository":
        path = candidate / "README.md"
        path.write_text(
            path.read_text().replace(
                "https://github.com/hzjanuary/open-companion",
                "https://example.invalid/source",
            )
        )
    result = run(candidate)
    assert result.returncode == 1
    assert "Public release validation failed:" in result.stderr
    assert "Traceback" not in result.stderr


def test_bad_metadata_does_not_echo_values(candidate: Path) -> None:
    canary = "PRIVATE-METADATA-CANARY"
    (candidate / "pyproject.toml").write_text(f"invalid = {canary}\n")
    result = run(candidate)
    assert result.returncode == 1
    assert canary not in result.stdout + result.stderr


def test_historical_names_and_arbitrary_fixtures_are_not_rewritten(
    candidate: Path,
) -> None:
    path = candidate / "docs/decisions/retired-name-history.md"
    path.write_text("# Historical record\n\nLumi was the working name.\n")
    fixture = candidate / "backend/tests/test_conversation_normalizer.py"
    before = fixture.read_bytes()
    result = run(candidate)
    assert result.returncode == 0, result.stderr
    assert fixture.read_bytes() == before
    assert path.read_text().endswith("Lumi was the working name.\n")


def test_heading_anchors_handle_fences_punctuation_and_duplicate_headings() -> None:
    assert release.heading_anchors(
        "# What is January?\n## Setup\n## Setup\n```text\n# Not a heading\n```\n"
    ) == {"what-is-january", "setup", "setup-1"}


def test_validator_has_no_external_process_or_network_imports() -> None:
    import ast

    tree = ast.parse(SCRIPT.read_text())
    modules = {
        name.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for name in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not modules & {"subprocess", "socket", "httpx", "requests", "http"}
