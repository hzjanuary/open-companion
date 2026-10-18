#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_root/scripts/lib/resolve-uv.sh"
uv_bin="$(resolve_uv "$project_root")"
export PYTHONPATH="$project_root/backend${PYTHONPATH:+:$PYTHONPATH}"

if [[ "${1:-}" != "--live" ]]; then
  printf '%s\n' "Configuration-only check passed when Settings loads. Use --live to send one synthetic structured request."
  "$uv_bin" run python -c 'from app.core.config import Settings; settings = Settings(); (_ for _ in ()).throw(SystemExit("Set JANUARY_LLM_ENABLED=true and provider model/key configuration before verification.")) if not settings.llm_enabled else print(f"provider={settings.llm_primary_provider} model=configured")'
  exit 0
fi

"$uv_bin" run python - <<'PY'
import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.application.context import ContextMessage, ConversationContext
from app.application.prompting import build_generation_request
from app.application.response_plan import ResponsePlanPolicy
from app.application.planning_service import generate_validated_plan
from app.core.config import Settings
from app.domain.planning import ProviderId, StickerIntent
from app.infrastructure.model_providers import create_model_provider

async def main() -> None:
    settings = Settings()
    if not settings.llm_enabled or not settings.llm_live_verification_enabled:
        raise SystemExit("Enable JANUARY_LLM_ENABLED and JANUARY_LLM_LIVE_VERIFICATION_ENABLED before --live.")
    current = ContextMessage(uuid4(), uuid4(), uuid4(), None, "hello", datetime.now(UTC), None, "Verification", True, False)
    request = build_generation_request(planning_job_id=uuid4(), context=ConversationContext(current, (), ()), prompt_version=settings.prompt_version, response_schema_version=settings.response_plan_schema_version, maximum_output_tokens=64, conversation_type="private", response_mode="mention_only")
    provider = create_model_provider(settings, ProviderId(settings.llm_primary_provider))
    try:
        result = await generate_validated_plan(request, ResponsePlanPolicy(settings.response_plan_text_limit, frozenset(StickerIntent)), provider, None, 1, 0)
        if result.candidate is None:
            raise SystemExit("Provider response did not pass local schema validation.")
        print(f"provider={provider.provider_id.value} model={provider.model} schema_validation=passed")
    finally:
        await provider.aclose()

asyncio.run(main())
PY
