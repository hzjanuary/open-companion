#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"

"$uv_bin" run python - "$project_root" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

root = Path(sys.argv[1])
zalo = root / "docs/platforms/zalo"
required_files = [
    root / ".env.zalo-verification.example",
    root / "docs/product/specs/SPEC-014-zalo-operator-verification-gate.md",
    zalo / "operator-verification-plan.md",
    zalo / "operator-verification-results.yaml",
    zalo / "operator-verification-report.md",
    zalo / "redaction-policy.md",
]
missing = [str(path.relative_to(root)) for path in required_files if not path.is_file()]
if missing:
    raise SystemExit(f"missing SPEC-014 artifacts: {', '.join(missing)}")

ignore_rules = (root / ".gitignore").read_text()
for ignored_path in (".env.zalo-verification.local", ".local/zalo-verification/"):
    if ignored_path not in ignore_rules:
        raise SystemExit(f"local verification path is not ignored: {ignored_path}")
example_values = {}
for line in (root / ".env.zalo-verification.example").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        example_values[key] = value
expected_example_keys = {
    "JANUARY_ZALO_VERIFY_ENVIRONMENT", "JANUARY_ZALO_VERIFY_APP_ID",
    "JANUARY_ZALO_VERIFY_OA_ID", "JANUARY_ZALO_VERIFY_ACCESS_TOKEN",
    "JANUARY_ZALO_VERIFY_REFRESH_TOKEN", "JANUARY_ZALO_VERIFY_APP_SECRET",
    "JANUARY_ZALO_VERIFY_WEBHOOK_BASE_URL", "JANUARY_ZALO_VERIFY_TEST_USER_ID",
    "JANUARY_ZALO_VERIFY_TEST_GMF_ID",
}
if set(example_values) != expected_example_keys:
    raise SystemExit("verification example has unexpected or missing variable names")
if example_values.pop("JANUARY_ZALO_VERIFY_ENVIRONMENT") != "test" or any(example_values.values()):
    raise SystemExit("verification example must contain only the test marker and blank placeholders")

results = yaml.safe_load((zalo / "operator-verification-results.yaml").read_text())
sources = yaml.safe_load((zalo / "official-sources.yaml").read_text())
if not isinstance(results, dict) or not isinstance(sources, dict):
    raise SystemExit("verification results and source register must be YAML mappings")
if results.get("spec") != "SPEC-014":
    raise SystemExit("verification result spec must be SPEC-014")
if results.get("baseline_commit") != "private-source-checkpoint-omitted":
    raise SystemExit("verification baseline checkpoint mismatch")
if results.get("status") not in {"NOT_STARTED", "IN_PROGRESS", "COMPLETE", "BLOCKED"}:
    raise SystemExit("invalid verification status")
if results.get("environment") != "dedicated_nonproduction":
    raise SystemExit("verification environment must be dedicated_nonproduction")
if results.get("operator_live_verification") not in {True, False}:
    raise SystemExit("operator_live_verification must be boolean")
decisions = {
    "GO_OA_DIRECT", "GO_OA_DIRECT_AND_GMF", "LIMITED_GO_OA_DIRECT",
    "LIMITED_GO_GMF", "NO_GO_ZALO", "STILL_BLOCKED",
}
if results.get("decision") not in decisions:
    raise SystemExit("invalid SPEC-014 decision")
if results.get("decision") == "STILL_BLOCKED" and results.get("status") != "BLOCKED":
    raise SystemExit("STILL_BLOCKED requires BLOCKED result status")
operator_environment = results.get("operator_environment_update")
if not isinstance(operator_environment, dict) or not all(
    key in operator_environment
    for key in (
        "dedicated_oa_app_available",
        "personal_accounts_permitted_as_test_participants_only",
        "personal_account_runtime_identity_permitted",
        "notes",
    )
):
    raise SystemExit("operator environment boundary is incomplete or unsafe")
if operator_environment["personal_account_runtime_identity_permitted"] is not False:
    raise SystemExit("personal accounts can never be a January runtime identity")
source_refresh = results.get("source_refresh")
if not isinstance(source_refresh, dict) or not all(
    key in source_refresh for key in ("checked_at", "changed_since_spec_013", "notes")
):
    raise SystemExit("results need a structured source_refresh record")

source_ids = {source.get("id") for source in sources.get("sources", []) if isinstance(source, dict)}
check_ids = {
    "AUTH-001", "WEBHOOK-001", "OA-DIRECT-001", "GMF-001", "GMF-002",
    "PRIVATE-GROUP-001", "COMMERCIAL-001",
}
checks = results.get("checks")
if not isinstance(checks, dict) or set(checks) != check_ids:
    raise SystemExit("verification checks must contain each required ID exactly once")
check_statuses = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}
for check_id, check in checks.items():
    if not isinstance(check, dict) or check.get("status") not in check_statuses:
        raise SystemExit(f"invalid status for {check_id}")
    for field in (
        "test_preconditions", "operator_action", "observed_result",
        "official_source_ids", "confidence", "product_implication", "follow_up",
    ):
        if not check.get(field):
            raise SystemExit(f"{check_id} needs {field}")
    if check["confidence"] not in {"high", "medium", "low"}:
        raise SystemExit(f"invalid confidence for {check_id}")
    refs = check["official_source_ids"]
    if not isinstance(refs, list) or not refs or not all(ref in source_ids for ref in refs):
        raise SystemExit(f"invalid official_source_ids for {check_id}")
if not operator_environment["dedicated_oa_app_available"] and any(
    check["status"] != "NOT_RUN"
    for check_id, check in checks.items()
    if check_id != "PRIVATE-GROUP-001"
):
    raise SystemExit("credentialed checks require a dedicated OA/app")
if results["operator_live_verification"] is False and any(
    check["status"] != "NOT_RUN" for check in checks.values()
):
    raise SystemExit("unexecuted live verification must keep every check NOT_RUN")

privacy = results.get("privacy")
if privacy != {
    "credentials_committed": False,
    "raw_payloads_committed": False,
    "personal_data_committed": False,
}:
    raise SystemExit("privacy record must explicitly deny committed sensitive evidence")

scan_paths = required_files + [root / "docs/platforms/zalo/capability-matrix.yaml"]
credential_pattern = re.compile(
    r"(?i)(?:client[_-]?secret|app[_-]?secret|access[_-]?token|refresh[_-]?token|authorization[_-]?code|api[_-]?key)[ \t]*[:=][ \t]*['\"]?[a-z0-9._-]{12,}|bearer[ \t]+[a-z0-9._-]{12,}"
)
for path in scan_paths:
    if credential_pattern.search(path.read_text()):
        raise SystemExit(f"credential-like value found in {path.relative_to(root)}")

def production_matches(needle: str) -> list[str]:
    matches = []
    for path in sorted((root / "backend/app").rglob("*.py")):
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if needle in line:
                matches.append(f"{path.relative_to(root)}:{line_number}:{line}")
    return matches


# Negative tests deliberately pass the pre-existing platform-neutral enum value
# through Telegram policies to prove fail-closed behavior. The freeze applies to
# production runtime use, which is the surface this validator owns.
platform_zalo = production_matches("Platform.ZALO")
if platform_zalo:
    raise SystemExit(
        "production Platform.ZALO use is prohibited in SPEC-014:\n"
        + "\n".join(platform_zalo)
    )
zalo_settings = production_matches("JANUARY_ZALO")
if zalo_settings:
    raise SystemExit(
        "production app configuration must not contain Zalo settings:\n"
        + "\n".join(zalo_settings)
    )

# Later accepted specifications may change other repository surfaces. The
# production `Platform.ZALO` and `JANUARY_ZALO` guards above continue to forbid
# accidental Zalo runtime work while this operator gate is deferred. They use
# the candidate filesystem rather than Git so shallow and VCS-free runs prove
# the same contract.
print("Zalo operator verification artifacts: valid")
PY
