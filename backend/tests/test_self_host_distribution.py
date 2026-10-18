"""Distribution checks supplement real Compose rendering, not live bot proof."""

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "distribution_contract", ROOT / "scripts/self_host/validate_distribution.py"
)
assert spec is not None and spec.loader is not None
distribution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distribution)


def fixture_graph() -> dict:
    environment = {f"JANUARY_{key}": "true" for key in distribution.CONTROLS}
    environment.update(
        JANUARY_PROVIDER_GOVERNANCE_MODE="enforce",
        JANUARY_DATABASE_HOST="database",
        JANUARY_REDIS_URL="redis://redis:6379/0",
        JANUARY_QDRANT_URL="http://qdrant:6333",
        JANUARY_TELEGRAM_DELIVERY_MODE="polling",
        JANUARY_TELEGRAM_ENABLED="true",
        JANUARY_LLM_ENABLED="true",
        JANUARY_COMMAND_WORKER_ENABLED="true",
        JANUARY_OUTBOUND_DELIVERY_ENABLED="true",
    )
    for pair in distribution.OPTIONAL_SETTINGS.values():
        for key in pair:
            environment[f"JANUARY_{key}"] = "false"
    services = {
        name: {
            "environment": dict(environment),
            "restart": "unless-stopped",
            "depends_on": {
                "migration": {"condition": "service_completed_successfully"},
                "redis": {"condition": "service_healthy"},
            },
        }
        for name in distribution.CORE
    }
    for name in ("database", "redis", "backend"):
        services[name]["healthcheck"] = {"test": ["closed-fixture"]}
    services["database"]["volumes"] = [{"target": "/var/lib/postgresql/data"}]
    services["migration"] = {
        "command": ["alembic", "upgrade", distribution.HEAD],
        "restart": "no",
        "environment": {"JANUARY_DATABASE_HOST": "database"},
        "depends_on": {"database": {"condition": "service_healthy"}},
    }
    services["backend"]["ports"] = [
        {"host_ip": "127.0.0.1", "target": 8000, "published": "8000"}
    ]
    for name, module in distribution.WORKERS.items():
        if name in services:
            services[name]["command"] = ["python", "/app/self-host/runtime.py", module]
    return {"services": services}


def test_actual_source_example_docs_and_launch_inventory() -> None:
    distribution.validate_sources()


def test_heading_links_handle_markup_and_duplicate_headings() -> None:
    content = '# 3. Choose `model` and limits\n## Same\n## Same\n<a id="manual"></a>\n'
    assert distribution.heading_anchors(content) == {
        "3-choose-model-and-limits",
        "same",
        "same-1",
        "manual",
    }


def test_closed_reference_graph_and_webhook_exclusion() -> None:
    graph = fixture_graph()
    distribution.validate_rendered(graph, ("polling",))
    del graph["services"]["poller"]
    for name, service in graph["services"].items():
        if name in distribution.WORKERS or name == "backend":
            service["environment"]["JANUARY_TELEGRAM_DELIVERY_MODE"] = "webhook"
    distribution.validate_rendered(graph, ("webhook",))


def test_both_ingress_profiles_are_not_an_accepted_distribution() -> None:
    with pytest.raises(ValueError, match="exactly one ingress"):
        distribution.validate_rendered(fixture_graph(), ("polling", "webhook"))


@pytest.mark.parametrize(
    "change",
    [
        "missing_worker",
        "public_database",
        "public_api",
        "no_persistence",
        "legacy_governance",
        "no_safety",
        "no_redis_health",
        "wrong_migration",
        "restart_migration",
        "live_migration_key",
        "unknown_worker",
        "hidden_qdrant",
        "wrong_delivery_mode",
        "half_enabled_optional",
        "disabled_outbound",
    ],
)
def test_mutated_graph_fails_closed(change: str) -> None:
    graph = copy.deepcopy(fixture_graph())
    services = graph["services"]
    if change == "missing_worker":
        del services["planning-worker"]
    elif change == "public_database":
        services["database"]["ports"] = [{"target": 5432, "published": "5432"}]
    elif change == "public_api":
        services["backend"]["ports"][0]["host_ip"] = "0.0.0.0"
    elif change == "no_persistence":
        services["database"]["volumes"][0]["target"] = "/discarded"
    elif change == "legacy_governance":
        services["planning-worker"]["environment"][
            "JANUARY_PROVIDER_GOVERNANCE_MODE"
        ] = "legacy"
    elif change == "no_safety":
        services["outbound-worker"]["environment"][
            "JANUARY_SAFETY_MODERATION_ENABLED"
        ] = "false"
    elif change == "no_redis_health":
        services["conversation-worker"]["depends_on"]["redis"]["condition"] = (
            "service_started"
        )
    elif change == "wrong_migration":
        services["migration"]["command"] = ["alembic", "upgrade", "head"]
    elif change == "restart_migration":
        services["migration"]["restart"] = "always"
    elif change == "live_migration_key":
        services["migration"]["environment"]["JANUARY_TELEGRAM_BOT_TOKEN"] = (
            "closed-canary"
        )
    elif change == "unknown_worker":
        services["poller"]["command"][-1] = "not_a_runtime"
    elif change == "hidden_qdrant":
        services["qdrant"] = {}
    elif change == "wrong_delivery_mode":
        services["backend"]["environment"]["JANUARY_TELEGRAM_DELIVERY_MODE"] = "webhook"
    elif change == "half_enabled_optional":
        services["backend"]["environment"]["JANUARY_SEMANTIC_MEMORY_ENABLED"] = "true"
    elif change == "disabled_outbound":
        services["outbound-worker"]["environment"][
            "JANUARY_OUTBOUND_DELIVERY_ENABLED"
        ] = "false"
    with pytest.raises(ValueError):
        distribution.validate_rendered(graph, ("polling",))
