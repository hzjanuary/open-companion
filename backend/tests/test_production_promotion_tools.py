import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/production-config-fingerprint.sh"


def fingerprint(**overrides: str) -> subprocess.CompletedProcess[str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("JANUARY_")
    }
    environment.update(overrides)
    return subprocess.run(
        [str(SCRIPT)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_fingerprint_is_deterministic_and_content_safe() -> None:
    first = fingerprint()
    second = fingerprint()
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    result = json.loads(first.stdout)
    assert result["schema_version"] == 1
    assert len(result["sha256"]) == 64
    assert set(result) == {"schema_version", "scope", "sha256"}


def test_secret_rotation_does_not_hash_or_emit_secret_values() -> None:
    first = fingerprint(JANUARY_LLM_OPENAI_API_KEY="promotion-fixture-first")
    second = fingerprint(JANUARY_LLM_OPENAI_API_KEY="promotion-fixture-second")
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    for result in (first, second):
        assert "promotion-fixture" not in result.stdout + result.stderr


def test_secret_injection_presence_changes_identity() -> None:
    absent = fingerprint()
    present = fingerprint(JANUARY_LLM_OPENAI_API_KEY="promotion-fixture")
    assert absent.returncode == present.returncode == 0
    assert absent.stdout != present.stdout


def test_normalized_runtime_metadata_changes_identity() -> None:
    default = fingerprint()
    changed = fingerprint(JANUARY_DATABASE_POOL_SIZE="7")
    assert default.returncode == changed.returncode == 0
    assert default.stdout != changed.stdout
    assert changed.stdout == fingerprint(JANUARY_DATABASE_POOL_SIZE="07").stdout


def test_invalid_settings_fail_closed_without_input_values() -> None:
    result = fingerprint(JANUARY_DATABASE_PORT="promotion-fixture-private-value")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "values redacted" in result.stderr
    assert "promotion-fixture-private-value" not in result.stderr


def test_fingerprint_scope_does_not_claim_complete_config_identity() -> None:
    result = fingerprint()
    assert result.returncode == 0
    assert json.loads(result.stdout)["scope"] == (
        "allowlisted runtime metadata and secret injection presence only"
    )
