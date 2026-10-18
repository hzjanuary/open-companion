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
from urllib.parse import urlparse

import yaml

root = Path(sys.argv[1])
platform = root / "docs/platforms/zalo"
required_files = [
    root / "docs/product/specs/SPEC-013-zalo-feasibility-spike-and-capability-matrix.md",
    platform / "official-source-register.md",
    platform / "official-sources.yaml",
    platform / "capability-matrix.yaml",
    platform / "telegram-parity-analysis.md",
    platform / "decision.md",
]
missing = [str(path.relative_to(root)) for path in required_files if not path.is_file()]
if missing:
    raise SystemExit(f"missing required feasibility artifacts: {', '.join(missing)}")

evidence_values = {
    "verified_official", "verified_official_policy", "official_but_login_required",
    "official_ambiguous", "not_documented", "not_supported",
    "requires_live_verification",
}
product_fit_values = {
    "supported", "supported_with_limits", "not_equivalent", "not_supported", "unknown",
}
decision_values = {"GO", "LIMITED_GO", "NO_GO", "BLOCKED_PENDING_OFFICIAL_VERIFICATION"}
confidence_values = {"high", "medium", "low"}
required_capabilities = """
official_account_identity application_identity access_token refresh_token token_rotation permission_review secret_storage_requirements test_or_sandbox_environment
direct_inbound_text direct_outbound_text direct_inbound_media direct_outbound_media direct_reply_to_message direct_message_id direct_user_id direct_conversation_id direct_message_ordering direct_duplicate_event_detection direct_edit_event direct_delete_or_recall_event
webhook_registration webhook_authentication_or_signature webhook_retry_behavior webhook_event_id webhook_message_event webhook_membership_event webhook_ordering_guarantee
group_surface_exists oa_can_create_group oa_can_join_group oa_can_receive_group_messages oa_can_send_group_messages group_message_id group_id group_member_id group_member_list group_member_role group_admin_role_check group_join_leave_events group_reply group_mentions group_threads_or_topics group_stickers group_media group_quota group_size_limit group_private_friend_use_case_fit
user_follow_requirement user_interaction_or_consent_requirement response_window proactive_message_rules message_type_classification monthly_or_package_entitlements per_user_limits per_oa_limits commercial_package_requirement oa_verification_requirement
january_mention_only_mode january_mention_and_name_mode january_ambient_selective_mode january_admin_commands january_user_preferences january_explicit_memory january_forget_me january_personality january_text_response january_reply january_mentions january_stickers january_safety_policy january_rate_limiting january_private_group_social_companion
""".split()

sources = yaml.safe_load((platform / "official-sources.yaml").read_text())
matrix = yaml.safe_load((platform / "capability-matrix.yaml").read_text())
if not isinstance(sources, dict) or not isinstance(sources.get("sources"), list):
    raise SystemExit("official-sources.yaml must contain a sources list")
source_ids: set[str] = set()
for source in sources["sources"]:
    if not isinstance(source, dict):
        raise SystemExit("source entry must be a mapping")
    source_id = source.get("id")
    if not isinstance(source_id, str) or source_id in source_ids:
        raise SystemExit("source IDs must be unique nonempty strings")
    source_ids.add(source_id)
    if source.get("evidence") not in evidence_values:
        raise SystemExit(f"invalid source evidence for {source_id}")
    for field in ("title", "publisher", "accessed_date", "login_required", "paraphrase", "caveats"):
        if not source.get(field):
            raise SystemExit(f"source {source_id} needs {field}")
    host = urlparse(str(source.get("url", ""))).hostname or ""
    if not (host == "zalo.me" or host.endswith(".zalo.me")):
        raise SystemExit(f"source {source_id} is not an official Zalo domain")

if matrix.get("platform") != "zalo":
    raise SystemExit("matrix platform must be zalo")
if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(matrix.get("researched_at", ""))):
    raise SystemExit("matrix researched_at must be YYYY-MM-DD")
if matrix.get("baseline_commit") != "private-source-checkpoint-omitted":
    raise SystemExit("matrix baseline_commit does not match SPEC-013 checkpoint")
if matrix.get("decision") not in decision_values:
    raise SystemExit("invalid decision")
if not isinstance(matrix.get("blockers"), list) or not isinstance(matrix.get("open_questions"), list):
    raise SystemExit("blockers and open_questions must be lists")
for blocker in matrix["blockers"]:
    if not isinstance(blocker, dict) or not all(blocker.get(key) for key in ("id", "severity", "notes")):
        raise SystemExit("every blocker needs id, severity, and notes")
for question in matrix["open_questions"]:
    if not isinstance(question, dict) or not all(question.get(key) for key in ("id", "question")):
        raise SystemExit("every open question needs id and question")
    if question.get("evidence") not in evidence_values:
        raise SystemExit("every open question needs valid evidence")
capabilities = matrix.get("capabilities")
if not isinstance(capabilities, dict):
    raise SystemExit("matrix capabilities must be a mapping")
if set(capabilities) != set(required_capabilities):
    missing = sorted(set(required_capabilities) - set(capabilities))
    extra = sorted(set(capabilities) - set(required_capabilities))
    raise SystemExit(f"capability IDs mismatch; missing={missing}; extra={extra}")
for capability_id, value in capabilities.items():
    if not isinstance(value, dict):
        raise SystemExit(f"{capability_id} must be a mapping")
    if value.get("evidence") not in evidence_values:
        raise SystemExit(f"invalid evidence for {capability_id}")
    if value.get("product_fit") not in product_fit_values:
        raise SystemExit(f"invalid product_fit for {capability_id}")
    if value.get("confidence") not in confidence_values:
        raise SystemExit(f"invalid confidence for {capability_id}")
    refs = value.get("source_ids")
    if not isinstance(refs, list) or not all(ref in source_ids for ref in refs):
        raise SystemExit(f"unresolved source_ids for {capability_id}")
    if value["evidence"] != "not_documented" and not refs:
        raise SystemExit(f"{capability_id} needs official source IDs")
    if not isinstance(value.get("notes"), str) or not isinstance(value.get("adapter_implication"), str):
        raise SystemExit(f"{capability_id} needs notes and adapter_implication")

credential_pattern = re.compile(
    r"(?i)(?:client[_-]?secret|api[_-]?key)\s*[:=]\s*['\"]?[a-z0-9._-]{12,}|bearer\s+[a-z0-9._-]{12,}"
)
for path in required_files:
    if credential_pattern.search(path.read_text()):
        raise SystemExit(f"credential-like value found in {path.relative_to(root)}")

# Later accepted specifications may modify runtime surfaces. The Zalo-specific
# guards above remain authoritative: no Zalo setting, enum, migration, or
# adapter may be introduced without a new accepted Zalo scope.
print("Zalo feasibility artifacts: valid")
PY
