"""Hermetic contract mutations and wrapper invocation against a fake uv only."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/graphify/validate.py"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    for relative in (
        "scripts/dev/graphify.sh",
        "scripts/lib/resolve-uv.sh",
        "scripts/validate-graphify-integration.sh",
        "scripts/graphify/validate.py",
        "pyproject.toml",
        "Dockerfile",
        "uv.lock",
        "compose.yaml",
        "compose.self-host.yaml",
        ".gitignore",
        ".dockerignore",
        ".graphifyignore",
        "AGENTS.md",
        "CONTRIBUTING.md",
        ".github/workflows/ci.yml",
        "docs/maintainers/graphify.md",
        "docs/runbooks/self-hosted-quickstart.md",
    ):
        dst = tmp_path / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, dst)
    return tmp_path


def check(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root)],
        env={"PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_vcs_free_contract_without_graph_or_tool(source: Path) -> None:
    assert not (source / ".git").exists()
    assert not (source / "graphify-out").exists()
    result = check(source)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("file", "old", "new"),
    [
        ("scripts/dev/graphify.sh", "graphifyy==0.9.74", "graphifyy"),
        ("pyproject.toml", "dependencies = [", 'dependencies = ["graphifyy==0.9.74",'),
        (".gitignore", "graphify-out/", "removed-derived-ignore/"),
        (
            "scripts/dev/graphify.sh",
            "extract . --code-only",
            "extract . --backend openai",
        ),
        ("AGENTS.md", "<!-- HARNESS:BEGIN -->", "<!-- REMOVED -->"),
        ("AGENTS.md", "system of", "graph overrides"),
        (
            ".github/workflows/ci.yml",
            "- run: ./scripts/validate.sh",
            "- run: uvx --from graphifyy==0.9.74 graphify extract .",
        ),
        (
            "scripts/dev/graphify.sh",
            "GRAPHIFY_NO_AUTO_REFRESH=1",
            "GRAPHIFY_NO_AUTO_REFRESH=0",
        ),
        (
            "CONTRIBUTING.md",
            "Contributors can work without Graphify.",
            "Graphify required.",
        ),
        (".graphifyignore", ".env.*", ".env.safe"),
    ],
)
def test_isolated_failure_detection(
    source: Path, file: str, old: str, new: str
) -> None:
    p = source / file
    content = p.read_text()
    assert old in content
    p.write_text(content.replace(old, new, 1))
    result = check(source)
    assert result.returncode != 0
    assert "FAIL" in result.stderr


def test_ignored_graph_does_not_fail_contract(source: Path) -> None:
    out = source / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text("synthetic dirty stale graph")
    assert check(source).returncode == 0


@pytest.mark.parametrize("tracked", [False, True])
def test_optional_index_check_rejects_force_added_graph(
    source: Path,
    tracked: bool,
) -> None:
    (source / ".git").mkdir()
    fake_bin = source / "fake-git"
    fake_bin.mkdir()
    git = fake_bin / "git"
    output = "graphify-out/graph.json" if tracked else ""
    git.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write({output!r})\n")
    git.chmod(0o755)
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(source)],
        env={"PATH": str(fake_bin), "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is (not tracked)


def run_wrapper(source: Path, *args: str) -> subprocess.CompletedProcess[str]:
    fake_bin = source / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'args':sys.argv[1:], 'cwd':os.getcwd(), "
        "'env':dict(os.environ)}))\n"
    )
    fake_uv.chmod(0o755)
    return subprocess.run(
        ["/bin/bash", str(source / "scripts/dev/graphify.sh"), *args],
        cwd=source / "docs",
        env={
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "HOME": str(source),
            "OPENAI_API_KEY": "synthetic-not-a-key",
            "GRAPHIFY_OUT": "elsewhere",
            "GRAPHIFY_QUERY_LOG_ENABLE": "1",
            "GRAPHIFY_NO_AUTO_REFRESH": "0",
        },
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("command", ["build", "update"])
def test_safe_build_update_and_environment(source: Path, command: str) -> None:
    result = run_wrapper(source, command)
    assert result.returncode == 0, result.stderr
    recorded = json.loads(result.stdout)
    assert recorded["args"] == [
        "tool",
        "run",
        "--from",
        "graphifyy==0.9.74",
        "graphify",
        "extract",
        ".",
        "--code-only",
    ]
    assert recorded["cwd"] == str(source)
    env = recorded["env"]
    assert "OPENAI_API_KEY" not in env
    assert "GRAPHIFY_QUERY_LOG_ENABLE" not in env
    assert env["GRAPHIFY_OUT"] == "graphify-out"
    assert env["GRAPHIFY_NO_AUTO_REFRESH"] == "1"
    assert env["GRAPHIFY_QUERY_LOG_DISABLE"] == "1"


@pytest.mark.parametrize(
    "args",
    [
        ("query", "synthetic question"),
        ("path", "From", "To"),
        ("explain", "Node"),
    ],
)
def test_graph_required_before_uv_and_explicit_path(
    source: Path, args: tuple[str, ...]
) -> None:
    missing = run_wrapper(source, *args)
    assert missing.returncode == 2
    assert "build first" in missing.stderr
    assert missing.stdout == ""
    out = source / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text("{}")
    result = run_wrapper(source, *args)
    assert result.returncode == 0
    assert json.loads(result.stdout)["args"][5:] == [
        *args,
        "--graph",
        "graphify-out/graph.json",
    ]


@pytest.mark.parametrize("command", ["status", "version"])
def test_status_version_do_not_resolve_tool(source: Path, command: str) -> None:
    result = run_wrapper(source, command)
    assert result.returncode == 0
    assert '"args"' not in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("build", "--backend", "openai"),
        ("install",),
        ("query", "--graph"),
        ("path", "a"),
    ],
)
def test_reject_widened_interface(source: Path, args: tuple[str, ...]) -> None:
    assert run_wrapper(source, *args).returncode == 2


def test_symlinked_output_rejected(source: Path) -> None:
    (source / "graphify-out").symlink_to(source / "docs", target_is_directory=True)
    result = run_wrapper(source, "build")
    assert result.returncode == 2
    assert "symlink" in result.stderr


def test_vcs_free_eval_inventory_preserves_source_and_excludes_local_state(
    tmp_path: Path,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "eval_source_inventory", ROOT / "scripts/lib/source-files.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".gitignore").write_text((ROOT / ".gitignore").read_text())
    for relative in (
        "backend/app/main.py",
        "docs/source.md",
        "scripts/check.sh",
        ".env.example",
        "graphify-out/graph.json",
        ".venv/key.py",
        ".env",
        ".env.production",
        ".git/config",
        ".runtime/data.json",
        "backend/__pycache__/cache.pyc",
    ):
        p = tmp_path / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic")
    assert module.source_files(tmp_path) == [
        ".env.example",
        ".gitignore",
        "backend/app/main.py",
        "docs/source.md",
        "scripts/check.sh",
    ]
    (tmp_path / ".gitignore").write_text("!unexpected\n")
    with pytest.raises(ValueError, match="unsupported"):
        module.source_files(tmp_path)


@pytest.mark.parametrize("owns_git_root", [False, True])
def test_source_inventory_does_not_use_ancestor_git(
    tmp_path: Path, owns_git_root: bool
) -> None:
    source = tmp_path / "export"
    source.mkdir()
    (source / ".gitignore").write_text("")
    (source / "keep.py").write_text("# synthetic source\n")
    for name in ("source-files.sh", "source-files.py"):
        destination = source / "scripts/lib" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts/lib" / name, destination)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = fake_bin / "git"
    top = str(source if owns_git_root else tmp_path)
    git.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"top = {top!r}\n"
        "if sys.argv[1:3] == ['rev-parse', '--show-toplevel']: print(top)\n"
        "elif sys.argv[1:3] == ['rev-parse', '--is-inside-work-tree']: print('true')\n"
        "elif sys.argv[1] == 'ls-files': sys.stdout.write('tracked-source.py\\0')\n"
        "else: sys.exit(2)\n"
    )
    git.chmod(0o755)
    uv = fake_bin / "uv"
    uv.write_text(
        f"#!{sys.executable}\nimport os, sys\n"
        "os.execv(sys.executable, [sys.executable, sys.argv[-1]])\n"
    )
    uv.chmod(0o755)
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1"; source_file_list "$2" "$3"',
            "proof",
            str(source / "scripts/lib/source-files.sh"),
            str(source),
            str(uv),
        ],
        env={"PATH": str(fake_bin)},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    expected = (
        ["tracked-source.py"]
        if owns_git_root
        else [
            ".gitignore",
            "keep.py",
            "scripts/lib/source-files.py",
            "scripts/lib/source-files.sh",
        ]
    )
    assert result.stdout.decode().rstrip("\0").split("\0") == expected
