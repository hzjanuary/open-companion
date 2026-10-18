"""Offline self-host packaging proof, never a daemon/startup/live acceptance test."""

import ast
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
HEAD = "0026_conversation_feedback"
CORE = {
    "database",
    "redis",
    "migration",
    "backend",
    "poller",
    "dispatcher",
    "conversation-worker",
    "planning-worker",
    "command-worker",
    "outbound-worker",
    "provider-governance-worker",
    "governance-worker",
    "retention-worker",
}
WORKERS = {
    "poller": "telegram_poller",
    "dispatcher": "ingress_outbox_dispatcher",
    "conversation-worker": "conversation_worker",
    "planning-worker": "response_planning_worker",
    "command-worker": "telegram_command_worker",
    "outbound-worker": "outbound_delivery_worker",
    "provider-governance-worker": "provider_governance_worker",
    "governance-worker": "governance_worker",
    "retention-worker": "retention_worker",
    "summary-worker": "conversation_summary_worker",
    "semantic-memory-worker": "semantic_memory_index_worker",
    "knowledge-index-worker": "knowledge_index_worker",
    "scheduler": "proactive_scheduler_worker",
}
OPTIONAL = {
    "qdrant": {"qdrant"},
    "summaries": {"summary-worker"},
    "semantic-memory": {"semantic-memory-worker", "qdrant"},
    "knowledge-rag": {"knowledge-index-worker", "qdrant"},
    "scheduling": {"scheduler"},
}
OPTIONAL_SETTINGS = {
    "summaries": ("CONVERSATION_SUMMARIES_ENABLED", "SUMMARY_WORKER_ENABLED"),
    "semantic-memory": ("SEMANTIC_MEMORY_ENABLED", "SEMANTIC_MEMORY_WORKER_ENABLED"),
    "knowledge-rag": ("KNOWLEDGE_RAG_ENABLED", "KNOWLEDGE_INDEX_WORKER_ENABLED"),
    "scheduling": ("PROACTIVE_SCHEDULING_ENABLED", "SCHEDULER_WORKER_ENABLED"),
}
CONTROLS = (
    "RATE_LIMIT_ENABLED",
    "PROVIDER_CONCURRENCY_ENABLED",
    "SAFETY_MODERATION_ENABLED",
    "PROVIDER_GOVERNANCE_WORKER_ENABLED",
    "CONTROL_PLANE_ENABLED",
    "DATA_GOVERNANCE_ENABLED",
    "GOVERNANCE_WORKER_ENABLED",
    "RETENTION_WORKER_ENABLED",
)
DOCS = (
    "README.md",
    "backend/README.md",
    "docs/README.md",
    "docs/ARCHITECTURE.md",
    "docs/product/README.md",
    "docs/product/SPEC.md",
    "SECURITY.md",
    "docs/product/self-hosted-deployment-profile.md",
    "docs/product/specs/SPEC-043-open-source-self-hosted-distribution-first-run.md",
    "docs/plans/handoff/SPEC-043-DESIGN-HANDOFF.md",
    "docs/runbooks/local-development.md",
    "docs/runbooks/self-hosted-quickstart.md",
    "docs/runbooks/self-hosted-vps.md",
    "docs/runbooks/self-hosted-upgrades.md",
    "docs/runbooks/self-hosted-troubleshooting.md",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def heading_anchors(content: str) -> set[str]:
    anchors = set(re.findall(r'\bid=["\']([^"\']+)["\']', content))
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+)$", content, re.M):
        plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", heading)
        plain = re.sub(r"<[^>]+>", "", plain)
        slug = re.sub(r"[^\w\s-]", "", plain.lower()).strip().replace(" ", "-")
        occurrence = counts.get(slug, 0)
        counts[slug] = occurrence + 1
        anchors.add(slug if occurrence == 0 else f"{slug}-{occurrence}")
    return anchors


def validate_rendered(document: dict, profiles: tuple[str, ...]) -> None:
    require(
        not {"polling", "webhook"} <= set(profiles), "Select exactly one ingress mode"
    )
    services = document["services"]
    expected = {"database", "redis"}
    if "polling" in profiles:
        expected |= CORE
    if "webhook" in profiles:
        expected |= CORE - {"poller"}
    if "setup" in profiles:
        expected |= {"migration", "operator-api"}
    if "tools" in profiles:
        expected.add("setup-tool")
    for profile, additional in OPTIONAL.items():
        if profile in profiles:
            expected |= additional
    require(
        set(services) == expected, "Selected profile has an incomplete service graph"
    )
    for name, service in services.items():
        if name == "backend":
            ports = service.get("ports", [])
            require(len(ports) == 1, "API must have one bounded host binding")
            require(
                ports[0].get("host_ip") == "127.0.0.1"
                and ports[0].get("target") == 8000
                and str(ports[0].get("published")) == "8000",
                "API default must bind loopback:8000",
            )
        else:
            require(not service.get("ports"), "Non-API service publishes a host port")
        if name in WORKERS or name in {"backend", "operator-api"}:
            values = service["environment"]
            if name != "operator-api":
                selected_mode = "webhook" if "webhook" in profiles else "polling"
                require(
                    values.get("JANUARY_TELEGRAM_DELIVERY_MODE") == selected_mode,
                    "Configured delivery mode disagrees with selected ingress profile",
                )
                require(
                    all(
                        values.get(f"JANUARY_{key}") == "true"
                        for key in (
                            "TELEGRAM_ENABLED",
                            "LLM_ENABLED",
                            "COMMAND_WORKER_ENABLED",
                            "OUTBOUND_DELIVERY_ENABLED",
                        )
                    ),
                    "Core chat worker path is disabled",
                )
                for profile, pair in OPTIONAL_SETTINGS.items():
                    enabled = "true" if profile in profiles else "false"
                    require(
                        all(values.get(f"JANUARY_{key}") == enabled for key in pair),
                        "Optional Settings/worker profile pair is incomplete",
                    )
            require(
                all(values.get(f"JANUARY_{key}") == "true" for key in CONTROLS),
                "A mandatory engineering control was weakened",
            )
            require(
                values.get("JANUARY_PROVIDER_GOVERNANCE_MODE") == "enforce",
                "Provider governance must enforce",
            )
            require(
                values.get("JANUARY_DATABASE_HOST") == "database"
                and values.get("JANUARY_REDIS_URL") == "redis://redis:6379/0"
                and values.get("JANUARY_QDRANT_URL") == "http://qdrant:6333",
                "Runtime dependency addresses must stay project-local",
            )
            require(
                service["depends_on"]["migration"]["condition"]
                == "service_completed_successfully",
                "Worker can start before migration success",
            )
            require(
                service["depends_on"]["redis"]["condition"] == "service_healthy",
                "Guarded runtime can start before Redis health",
            )
            require(service["restart"] == "unless-stopped", "Runtime restart contract")
            if name in WORKERS:
                require(
                    service["command"]
                    == ["python", "/app/self-host/runtime.py", WORKERS[name]],
                    "Worker must launch the existing stock runtime",
                )
                require(
                    (ROOT / f"backend/app/runtime/{WORKERS[name]}.py").is_file(),
                    "Worker references a missing runtime module",
                )
        if name in {"backend", "operator-api", "database", "redis"}:
            require(
                bool(service.get("healthcheck", {}).get("test")), "Healthcheck missing"
            )
    if "migration" in services:
        migration = services["migration"]
        require(
            migration["command"] == ["alembic", "upgrade", HEAD],
            "Wrong migration target",
        )
        require(migration["restart"] == "no", "Migration must be one-shot")
        require(
            migration["depends_on"]["database"]["condition"] == "service_healthy",
            "Migration requires healthy PostgreSQL",
        )
        require(
            all(
                key.startswith("JANUARY_DATABASE_") or key == "JANUARY_ENVIRONMENT"
                for key in migration["environment"]
            ),
            "Migration process received unrelated live credentials",
        )
    if "operator-api" in services:
        environment = services["operator-api"]["environment"]
        require(
            all(
                environment[f"JANUARY_{key}"] == "false"
                for key in (
                    "TELEGRAM_ENABLED",
                    "LLM_ENABLED",
                    "OUTBOUND_DELIVERY_ENABLED",
                    "TELEGRAM_MEDIA_ENABLED",
                    "TELEGRAM_VOICE_TTS_ENABLED",
                )
            )
            and environment["JANUARY_TELEGRAM_DELIVERY_MODE"] == "disabled",
            "Private setup API can perform ingress/generation/delivery",
        )
    if "setup-tool" in services:
        tool = services["setup-tool"]
        require(not tool.get("depends_on"), "Explicit setup tool starts dependencies")
        require(tool["restart"] == "no", "Explicit setup tool must be one-shot")
    require(
        services["database"]["volumes"][0]["target"] == "/var/lib/postgresql/data",
        "Authoritative PostgreSQL persistence missing",
    )
    require(
        not services["redis"].get("volumes"),
        "Redis must not masquerade as backup truth",
    )
    if "qdrant" in services:
        require(
            services["qdrant"]["volumes"][0]["target"] == "/qdrant/storage",
            "Optional derived index volume missing",
        )


def validate_sources() -> None:
    inventory = set(
        re.findall(r"^(JANUARY_[A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.M)
    )
    minimal = (ROOT / ".env.self-host.example").read_text()
    entries = dict(re.findall(r"^(JANUARY_[A-Z0-9_]+)=(.*)$", minimal, re.M))
    require(
        set(entries) <= inventory | {"JANUARY_HOST_PORT"}, "Unknown minimal config name"
    )
    require(
        len(entries) == len(re.findall(r"^JANUARY_", minimal, re.M)),
        "Duplicate minimal config",
    )
    for key, value in entries.items():
        if key.endswith(
            ("_API_KEY", "_BOT_TOKEN", "_PASSWORD", "_JWT_SECRET", "_SECRET_TOKEN")
        ):
            require(value == "", "A secret was supplied in a distribution example")
    for key in (
        "TELEGRAM_VOICE_TTS_ENABLED",
        "TELEGRAM_MEDIA_ENABLED",
        "CONVERSATION_SUMMARIES_ENABLED",
        "SUMMARY_WORKER_ENABLED",
        "SEMANTIC_MEMORY_ENABLED",
        "SEMANTIC_MEMORY_WORKER_ENABLED",
        "KNOWLEDGE_RAG_ENABLED",
        "KNOWLEDGE_INDEX_WORKER_ENABLED",
        "PROACTIVE_SCHEDULING_ENABLED",
        "SCHEDULER_WORKER_ENABLED",
    ):
        require(
            entries[f"JANUARY_{key}"] == "false",
            "Optional first-run dependency enabled",
        )
    policy = json.loads(
        (ROOT / "docs/examples/self-host-provider-policy.json").read_text()
    )
    require(
        policy["json_schema_supported"] is False,
        "Schema support must not be fabricated",
    )
    require(
        policy["input_microusd_per_million"] is None
        and policy["output_microusd_per_million"] is None
        and policy["budgets"][0]["amount"] is None,
        "Example must not invent price/spend authority",
    )
    for relative in DOCS:
        path = ROOT / relative
        content = path.read_text()
        for target in re.findall(r"\]\(([^)\s]+)\)", content):
            parsed = urlsplit(target.strip("<>"))
            if parsed.scheme or parsed.netloc:
                continue
            destination = path.parent / unquote(parsed.path) if parsed.path else path
            require(destination.exists(), f"Missing local link in {relative}: {target}")
            if parsed.fragment and destination.suffix == ".md":
                require(
                    unquote(parsed.fragment)
                    in heading_anchors(destination.read_text()),
                    f"Missing heading link in {relative}: {target}",
                )
        for module in set(re.findall(r"app\.runtime\.([a-z_]+)", content)):
            require(
                (ROOT / f"backend/app/runtime/{module}.py").is_file(),
                f"Documentation references missing runtime: {module}",
            )
    launcher = ast.parse((ROOT / "scripts/self_host/runtime.py").read_text())
    names = next(
        ast.literal_eval(node.value)
        for node in launcher.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "WORKERS"
            for target in node.targets
        )
    )
    require(
        set(names) == set(WORKERS.values()),
        "Compose and launcher worker inventory disagree",
    )
    for relative in (
        "scripts/self-host-doctor.sh",
        "scripts/self-host-compose.sh",
        "scripts/validate-self-hosted.sh",
    ):
        path = ROOT / relative
        require(
            path.stat().st_mode & 0o111 == 0o111, "Direct script lacks executable mode"
        )
        require(b"\r" not in path.read_bytes(), "Direct script requires LF")
    require(
        "USER january" in (ROOT / "Dockerfile").read_text(),
        "Non-root image boundary missing",
    )


def render(profiles: tuple[str, ...]) -> dict:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("JANUARY_")
    }
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-f",
        str(ROOT / "compose.self-host.yaml"),
    ]
    for profile in profiles:
        command.extend(("--profile", profile))
    command.extend(("config", "--format", "json"))
    # Synthetic mode/feature selection mirrors an operator's file without any
    # real secret, daemon or startup. NamedTemporaryFile owns a private 600 file.
    settings = {
        "JANUARY_TELEGRAM_DELIVERY_MODE": "webhook"
        if "webhook" in profiles
        else "polling"
    }
    for profile, pair in OPTIONAL_SETTINGS.items():
        for key in pair:
            settings[f"JANUARY_{key}"] = "true" if profile in profiles else "false"
    source = (ROOT / ".env.self-host.example").read_text()
    content = (
        "\n".join(
            f"{line.split('=', 1)[0]}={settings[line.split('=', 1)[0]]}"
            if line.split("=", 1)[0] in settings
            else line
            for line in source.splitlines()
        )
        + "\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".local"
    ) as fixture:
        fixture.write(content)
        fixture.flush()
        environment["JANUARY_SELF_HOST_ENV_FILE"] = fixture.name
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    require(
        result.returncode == 0,
        "Compose plugin cannot render the selected topology (details redacted)",
    )
    return json.loads(result.stdout)


def main() -> None:
    validate_sources()
    selected = [(), ("setup",), ("tools",), ("polling",), ("webhook",)]
    selected.extend(
        (mode, option) for mode in ("polling", "webhook") for option in OPTIONAL
    )
    selected.extend((mode, *OPTIONAL) for mode in ("polling", "webhook"))
    for profiles in selected:
        validate_rendered(render(profiles), profiles)
    print(
        f"Self-host distribution: {len(selected)} actual offline Compose topologies "
        "and source/doc contracts pass"
    )
    print(
        "Scope: no daemon/resources, migration, Telegram/provider/model download "
        "or live acceptance"
    )


if __name__ == "__main__":
    main()
