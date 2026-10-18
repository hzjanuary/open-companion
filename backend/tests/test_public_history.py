"""Offline history review with disposable synthetic repositories only."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/public_release/audit_history.py"
spec = importlib.util.spec_from_file_location("public_history", SCRIPT)
assert spec is not None and spec.loader is not None
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    ).strip()


def commit(root: Path) -> None:
    git(root, "add", "--all")
    git(
        root,
        "-c",
        "user.name=Synthetic Reviewer",
        "-c",
        "user.email=synthetic@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "Synthetic test change",
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "README.md").write_text("Synthetic source only.\n")
    commit(root)
    return root


def cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )


def test_clean_history_has_precise_coverage_without_approval(repository: Path) -> None:
    result = cli(repository)
    assert result.returncode == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["coverage"]["commits"] == 1
    assert report["coverage"]["object_types"] == {"blob": 1, "commit": 1, "tree": 1}
    assert report["coverage"]["historical_paths"] == 1
    assert report["coverage"]["deleted_paths"] == 0
    assert report["coverage"]["all_local_refs_and_HEAD"] is True
    assert report["publication_approval"] is False
    assert "OWNER REVIEW REQUIRED" in report["metadata"]["owner_gate"]
    assert "synthetic@example.invalid" not in result.stdout
    assert "Synthetic Reviewer" not in result.stdout


@pytest.mark.parametrize(
    ("category", "value"),
    [
        ("telegram-token", "123456789:" + "A" * 35),
        ("provider-token", "sk-proj-" + "a" * 32),
        ("provider-token", "AIza" + "b" * 35),
        ("provider-token", "gsk_" + "c" * 32),
        ("provider-token", "sk-or-v1-" + "d" * 32),
        ("provider-token", "ghp_" + "e" * 32),
        ("private-key", "-----BEGIN " + "RSA PRIVATE KEY-----"),
        ("credential-url", "postgresql://synthetic:synthetic-password@localhost/test"),
        ("jwt", "eyJ" + "a" * 12 + "." + "b" * 15 + "." + "c" * 15),
        ("credential-assignment", "WEBHOOK_SECRET=synthetic-sensitive-value"),
        ("platform-identifier", 'chat_id="123456789"'),
        ("platform-identifier", '"platform_user_id": "123456789"'),
        ("credential-assignment", '"password": "synthetic-db-secret"'),
        ("personal-checkout-path", "/home/synthetic-person/private-checkout/"),
        ("private-record", '"chat_history": [{"text": "synthetic only"}]'),
    ],
)
def test_deleted_content_is_reviewed_and_redacted(
    repository: Path,
    category: str,
    value: str,
) -> None:
    path = repository / "removed.txt"
    path.write_text(value + "\n")
    commit(repository)
    path.unlink()
    commit(repository)
    result = cli(repository)
    assert result.returncode == 1
    assert value not in result.stdout + result.stderr
    assert "removed.txt" not in result.stdout
    report = json.loads(result.stdout)
    assert category in {item["category"] for item in report["findings"]}
    assert report["coverage"]["commits"] == 3
    assert report["coverage"]["deleted_paths"] == 1
    assert report["unresolved"] > 0


def test_old_env_and_binary_remain_unreviewed(repository: Path) -> None:
    path = repository / ".env"
    path.write_text("SYNTHETIC=placeholder\n")
    binary = repository / "fixture.p12"
    binary.write_bytes(b"\x00\xffsynthetic\x00")
    commit(repository)
    path.unlink()
    binary.unlink()
    commit(repository)
    report = history.audit(repository)
    assert report["unresolved"] >= 3
    assert {"high-risk-path", "non-text-review"}.issubset(
        {item["category"] for item in report["findings"]}
    )
    assert len(report["non_text_blobs"]) == 1
    assert report["coverage"]["deleted_paths"] == 2


def test_disposition_is_exact_and_never_a_path_allowlist(repository: Path) -> None:
    path = repository / "example.txt"
    path.write_text("sk-" + "x" * 32)
    commit(repository)
    report = history.audit(repository)
    dispositions = {
        item["id"]: {
            "disposition": "synthetic-fixture",
            "reason": "Reviewed synthetic example",
        }
        for item in report["findings"]
    }
    reviewed = history.audit(repository, dispositions=dispositions)
    assert reviewed["unresolved"] == 0
    assert reviewed["publication_approval"] is False
    assert all(item["automatic_detection"] for item in reviewed["findings"])
    path.write_text("sk-" + "y" * 32)
    commit(repository)
    assert history.audit(repository, dispositions=dispositions)["unresolved"] == 1


def test_disposition_cannot_ignore_unknown_findings(repository: Path) -> None:
    with pytest.raises(history.AuditError, match="unknown human disposition"):
        history.audit(
            repository, dispositions={"unknown": {"disposition": "false-positive"}}
        )


def test_missing_ref_coverage_fails_closed(repository: Path) -> None:
    git(repository, "branch", "other")
    result = cli(repository, "--ref", "refs/heads/main", "--ref", "HEAD")
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "COVERAGE_INCOMPLETE"


def test_shallow_history_fails_closed(repository: Path, tmp_path: Path) -> None:
    (repository / "second.txt").write_text("Synthetic second commit")
    commit(repository)
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "--depth=1", repository.as_uri(), str(shallow))
    result = cli(shallow)
    assert result.returncode == 2
    assert "shallow history" in result.stdout
    assert '"publication_approval": false' in result.stdout


def test_missing_object_fails_without_printing_git_stderr(repository: Path) -> None:
    oid = git(repository, "rev-parse", "HEAD:README.md")
    (repository / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
    result = cli(repository)
    assert result.returncode == 2
    assert "COVERAGE_INCOMPLETE" in result.stdout
    assert result.stderr == ""


def test_git_command_failure_is_safe(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], 1, b"", b"synthetic-sensitive-stderr")

    monkeypatch.setattr(history.subprocess, "run", fail)
    with pytest.raises(history.AuditError, match="git command failed") as caught:
        history.audit(repository)
    assert "synthetic-sensitive-stderr" not in str(caught.value)


def test_source_without_git_cannot_claim_history_coverage(tmp_path: Path) -> None:
    result = cli(tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["publication_approval"] is False


@pytest.mark.parametrize("enabled", ["true", "yes", "on", "1"])
def test_partial_clone_rejected_without_fetch(repository: Path, enabled: str) -> None:
    git(repository, "config", "remote.origin.promisor", enabled)
    result = cli(repository)
    assert result.returncode == 2
    assert "partial/promisor" in result.stdout


def test_empty_multiline_keys_do_not_capture_the_next_setting() -> None:
    content = b"OPENAI_API_KEY=\nGEMINI_API_KEY=\nPASSWORD=\nOTHER=synthetic\n"
    assert history.inspect_content("synthetic-object", content, []) == []


def test_owner_path_consent_cannot_dispose_a_credential(repository: Path) -> None:
    (repository / "example.txt").write_text("sk-" + "z" * 32)
    commit(repository)
    report = history.audit(repository)
    dispositions = {
        item["id"]: {"disposition": "owner-consent-required", "reason": "Owner gate"}
        for item in report["findings"]
    }
    with pytest.raises(history.AuditError, match="invalid human disposition"):
        history.audit(repository, dispositions=dispositions)


def test_noncommit_ref_fails_closed(repository: Path) -> None:
    oid = git(repository, "rev-parse", "HEAD:README.md")
    git(repository, "tag", "synthetic-blob-tag", oid)
    assert cli(repository).returncode == 2


def test_inherited_git_directory_cannot_redirect_scope(
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nonexistent-private-location"))
    monkeypatch.setenv("GIT_TRACE", str(tmp_path / "unexpected-trace"))
    assert history.audit(repository)["coverage"]["commits"] == 1
    assert not (tmp_path / "unexpected-trace").exists()
