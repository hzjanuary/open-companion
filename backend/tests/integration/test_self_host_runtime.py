"""Fresh actual Docker first run, polling/restart/dedup and webhook delivery.

Opt-in integration proof uses only a unique owned project, an already locally
built image, fresh volume and internal network. No real provider/Telegram call,
product fixture SQL, shared service, host Python app prerequisite or live data.
"""

import ipaddress
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "january-self-host:spec043-development"
TOKEN = "999999999:closed_spec043_bot_token"
KEY = "CLOSED-SPEC043-PROVIDER-CANARY"
WEBHOOK_SECRET = "CLOSED-SPEC043-WEBHOOK-CANARY"
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
SNAPSHOT = """
SELECT json_build_object(
 'head',(SELECT version_num FROM alembic_version),
 'inbox',(SELECT count(*) FROM incoming_platform_updates),
 'outbox',(SELECT count(*) FROM ingress_outbox_events WHERE status='published'),
 'conversations',(SELECT count(*) FROM conversations),
 'records',(SELECT count(*) FROM conversation_processing_records),
 'incoming',(SELECT count(*) FROM messages WHERE direction='incoming'),
 'outgoing',(SELECT count(*) FROM messages WHERE direction='outgoing'),
 'jobs',(SELECT count(*) FROM response_planning_jobs WHERE status='completed'),
 'plans',(SELECT count(*) FROM response_plans),
 'delivered',(SELECT count(*) FROM outbound_actions WHERE status='delivered'),
 'attempts',(SELECT count(*) FROM provider_usage_attempts
             WHERE state='io_complete' AND provider_outcome='success'),
 'consumed',(SELECT coalesce(sum(consumed_amount),0) FROM provider_budget_windows),
 'reserved',(SELECT coalesce(sum(reserved_amount),0) FROM provider_budget_windows),
 'cursor',(SELECT next_offset FROM polling_cursors),
 'cursors',(SELECT count(*) FROM polling_cursors),
 'safety',(SELECT count(*) FROM safety_policy_decisions),
 'rate',(SELECT count(*) FROM rate_limit_events WHERE allowed=true),
 'capabilities',(SELECT count(*) FROM provider_capabilities),
 'prices',(SELECT count(*) FROM provider_price_revisions),
 'budgets',(SELECT count(*) FROM provider_budget_revisions
            WHERE enabled=true AND mode='hard'),
 'recoveries',(SELECT count(*) FROM operational_recovery_items)
)
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def execute(command: list[str], *, timeout: int = 120) -> str:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("JANUARY_")
    }
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    require(
        result.returncode == 0, "Owned runtime proof command failed (details redacted)"
    )
    return result.stdout


def configuration(path: Path, updates: dict[str, str]) -> None:
    source = path.read_text()
    lines = source.splitlines()
    present = {line.split("=", 1)[0] for line in lines if line.startswith("JANUARY_")}
    path.write_text(
        "\n".join(
            f"{line.split('=', 1)[0]}={updates[line.split('=', 1)[0]]}"
            if line.split("=", 1)[0] in updates
            else line
            for line in lines
        )
        + "\n"
        + "\n".join(
            f"{key}={value}" for key, value in updates.items() if key not in present
        )
        + "\n"
    )
    path.chmod(0o600)


def values(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text().splitlines()
        if line.startswith("JANUARY_")
    )


def wait_for(observe, accept, *, timeout: int = 60):
    deadline = time.monotonic() + timeout
    last = observe()
    while not accept(last):
        require(
            time.monotonic() < deadline,
            "Bounded runtime observation did not reach the required state; "
            f"aggregate observation: {json.dumps(last, sort_keys=True)}",
        )
        threading.Event().wait(0.2)
        last = observe()
    return last


@pytest.mark.integration
def test_fresh_docker_first_run_polling_restart_webhook_and_governed_delivery(
    tmp_path: Path,
) -> None:
    project = "spec043-runtime-" + uuid4().hex[:12]
    require(
        project.removeprefix("spec043-runtime-").isalnum(), "Invalid owned project name"
    )
    for resource in ("ps", "volume ls", "network ls"):
        command = ["docker", *resource.split()]
        if resource == "ps":
            command.append("-a")
        command += [
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.ID}}",
        ]
        require(
            execute(command).strip() == "",
            "Proof project must have no existing resources",
        )
    execute(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"])
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config = tmp_path / ".env.self-host"
    config.write_text((ROOT / ".env.self-host.example").read_text())
    config.chmod(0o600)
    configuration(
        config,
        {
            "JANUARY_BACKEND_IMAGE": IMAGE,
            "JANUARY_HOST_PORT": str(port),
            "JANUARY_TELEGRAM_BOT_TOKEN": TOKEN,
            "JANUARY_TELEGRAM_API_BASE_URL": "http://closed-io:8080",
            "JANUARY_TELEGRAM_POLL_TIMEOUT_SECONDS": "2",
            "JANUARY_LLM_OPENAI_MODEL": "closed-schema-model",
            "JANUARY_LLM_OPENAI_API_KEY": KEY,
            "JANUARY_LLM_OPENAI_BASE_URL": "http://closed-io:8080/v1",
        },
    )
    policy = tmp_path / "provider-policy.json"
    body = json.loads(
        (ROOT / "docs/examples/self-host-provider-policy.json").read_text()
    )
    body.update(
        json_schema_supported=True,
        input_microusd_per_million=1_000_000,
        output_microusd_per_million=2_000_000,
        health={
            "observation_window_seconds": 300,
            "degraded_threshold": 3,
            "unavailable_threshold": 5,
            "recovery_success_threshold": 2,
            "stale_after_seconds": 3600,
        },
        budgets=[
            {
                "measurement": "requests",
                "window_kind": "daily_utc",
                "amount": 10,
                "alert_threshold_bps": 8000,
            }
        ],
    )
    policy.write_text(json.dumps(body))
    policy.chmod(0o600)
    override = tmp_path / "closed.yaml"
    override.write_text(f"""services:
  setup-tool:
    volumes:
      - {tmp_path}:/operator
  closed-io:
    image: {IMAGE}
    command: [python, /proof/self_host_http.py]
    volumes:
      - {ROOT / "backend/tests/fixtures/self_host_http.py"}:/proof/self_host_http.py:ro
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - >-
          import urllib.request;
          urllib.request.urlopen('http://127.0.0.1:8080/proof/state', timeout=2)
      interval: 1s
      timeout: 3s
      retries: 20
    restart: 'no'
networks:
  default:
    internal: true
""")
    base = [
        str(ROOT / "scripts/self-host-compose.sh"),
        "--config",
        str(config),
        "-p",
        project,
        "-f",
        str(override),
    ]

    def compose(*arguments: str) -> str:
        return execute([*base, *arguments])

    def tool(operation: str, *extra: str) -> str:
        return compose(
            "--profile",
            "tools",
            "run",
            "--rm",
            "--no-deps",
            "--pull",
            "never",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "setup-tool",
            "python",
            "/app/self-host/setup_operator.py",
            operation,
            "--config",
            "/operator/.env.self-host",
            "--policy",
            "/operator/provider-policy.json",
            *extra,
        )

    def doctor(*extra: str) -> None:
        execute(
            [
                str(ROOT / "scripts/self-host-doctor.sh"),
                "--offline",
                "--config",
                str(config),
                "--policy",
                str(policy),
                *extra,
            ]
        )

    def snapshot() -> dict:
        output = compose(
            "exec",
            "-T",
            "database",
            "sh",
            "-c",
            'exec psql -X -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" '
            '-d "$POSTGRES_DB" -c "$1"',
            "proof",
            SNAPSHOT,
        )
        return json.loads(output)

    def boundary(*, arm: bool = False) -> dict:
        request = (
            "urllib.request.Request('http://127.0.0.1:8080/proof/arm',data=b'{}',headers={'Content-Type':'application/json'})"
            if arm
            else "'http://127.0.0.1:8080/proof/state'"
        )
        output = compose(
            "exec",
            "-T",
            "closed-io",
            "python",
            "-c",
            "import urllib.request; "
            f"print(urllib.request.urlopen({request},timeout=5).read().decode())",
        )
        return json.loads(output)

    def running(mode: str) -> None:
        rows = [
            json.loads(line)
            for line in compose(
                "--profile", mode, "ps", "--all", "--format", "json"
            ).splitlines()
            if line
        ]
        active = {row["Service"] for row in rows if row["State"] == "running"}
        expected = CORE - {"migration"} | {"closed-io"}
        if mode == "webhook":
            expected -= {"poller"}
        require(
            active == expected, "Actual required running worker graph is incomplete"
        )
        ids = execute(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ]
        ).split()
        inspected = json.loads(execute(["docker", "inspect", *ids]))
        require(
            all(row["RestartCount"] == 0 for row in inspected),
            "A required service is crash-restarting",
        )
        require(
            all(
                set(row["NetworkSettings"]["Networks"]) == {f"{project}_default"}
                for row in inspected
            ),
            "Proof acquired an external network",
        )
        network = json.loads(
            execute(["docker", "network", "inspect", f"{project}_default"])
        )[0]
        require(
            network["Internal"] is True, "Proof network must prohibit external egress"
        )
        for row in inspected:
            service = row["Config"]["Labels"]["com.docker.compose.service"]
            if service in {"database", "redis", "closed-io"}:
                require(
                    not row["HostConfig"]["PortBindings"],
                    "Proof data/fake service published a port",
                )

    owned = False
    retained_coordination_volumes: list[str] = []

    def remove_retained_coordination() -> None:
        # Only mounts observed on this exact owned Redis container qualify.
        # Never sweep anonymous volumes or infer ownership from a broad delta.
        for volume in retained_coordination_volumes:
            require(
                execute(["docker", "ps", "-aq", "--filter", f"volume={volume}"]).strip()
                == "",
                "Owned disposable Redis volume is still referenced",
            )
            execute(["docker", "volume", "rm", volume])
        retained_coordination_volumes.clear()

    try:
        doctor("--phase", "template")
        owned = True
        tool("init")
        initialized = config.read_bytes()
        tool("init")
        require(
            config.read_bytes() == initialized, "Init overwrote private configuration"
        )
        doctor("--phase", "setup", "--typed")
        compose("up", "-d", "--wait", "closed-io")
        compose("--profile", "setup", "up", "-d", "--wait", "operator-api")
        initial = snapshot()
        require(
            initial["head"] == "0026_conversation_feedback"
            and initial["inbox"] == 0
            and initial["capabilities"] == 0
            and initial["conversations"] == 0,
            "Fresh migration is not a base-to-head empty operational installation",
        )
        tool("setup", "--confirm-operator-setup", "--confirm-live-telegram")
        recorded = values(config)
        connection = str(UUID(recorded["JANUARY_TELEGRAM_PLATFORM_CONNECTION_ID"]))
        tenant = str(UUID(recorded["JANUARY_TELEGRAM_TENANT_ID"]))
        require(
            recorded["JANUARY_CONTROL_PLANE_DEPLOYMENT_BOOTSTRAP_SUBJECTS"] == "[]",
            "Bootstrap subjects not cleared",
        )
        tool("setup", "--confirm-operator-setup", "--confirm-live-telegram")
        authority = compose(
            "exec",
            "-T",
            "database",
            "sh",
            "-c",
            'exec psql -X -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" '
            '-d "$POSTGRES_DB" -c "$1"',
            "proof",
            "SELECT count(*) FROM platform_connections c "
            "JOIN assistants a ON a.id=c.assistant_id AND a.tenant_id=c.tenant_id "
            "JOIN control_tenants t ON t.id=c.tenant_id "
            f"WHERE c.id='{connection}' AND t.id='{tenant}' "
            "AND c.status='active' AND a.status='active' AND t.status='active'",
        )
        require(
            authority.strip() == "1",
            "Canonical active tenant/Assistant/connection authority missing",
        )
        setup = snapshot()
        require(
            (setup["capabilities"], setup["prices"], setup["budgets"]) == (1, 1, 1),
            "Repeated setup duplicated policies",
        )
        require(
            boundary()["counts"].get("generation", 0) == 0
            and boundary()["counts"].get("sendMessage", 0) == 0,
            "Setup performed generation/delivery",
        )
        compose("--profile", "setup", "stop", "operator-api")
        doctor("--typed")
        compose("--profile", "polling", "up", "-d", "--wait")
        running("polling")
        backend_id = compose("ps", "-q", "backend").strip()
        address = execute(
            [
                "docker",
                "inspect",
                "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                backend_id,
            ]
        ).strip()
        require(
            ipaddress.ip_address(address).is_private,
            "API probe must remain on the owned private network",
        )
        # Docker internal-only bridges on this engine do not publish ports.
        # Probe the exact owned API directly here; separately prove the guide's
        # default-network host publication below, with all I/O workers stopped.
        with httpx.Client(
            base_url=f"http://{address}:8000", timeout=10, trust_env=False
        ) as client:
            require(
                client.get("/live").status_code
                == client.get("/ready").status_code
                == 200,
                "Fresh live/ready checks failed",
            )
            require(
                client.get("/control/v1/me").status_code == 401,
                "Running control API became anonymous",
            )
            boundary(arm=True)
            first = wait_for(snapshot, lambda row: row["delivered"] == 1)
            require(
                all(
                    first[key] == 1
                    for key in (
                        "inbox",
                        "outbox",
                        "records",
                        "incoming",
                        "outgoing",
                        "jobs",
                        "plans",
                        "attempts",
                        "consumed",
                        "cursors",
                    )
                ),
                "Polling durable/governed flow is incomplete",
            )
            require(
                first["cursor"] == "7002"
                and first["reserved"] == first["recoveries"] == 0,
                "Polling cursor/accounting/recovery invariant failed",
            )
            require(
                first["safety"] > 0 and first["rate"] > 0,
                "Mandatory safety/rate path not observed",
            )
            poll_requests = boundary()["counts"].get("getUpdates", 0)
            compose("--profile", "polling", "restart", "poller")
            wait_for(
                boundary,
                lambda row: row["last_offset"] == 7002
                and row["counts"].get("getUpdates", 0) > poll_requests,
            )
            boundary(arm=True)
            wait_for(boundary, lambda row: row["counts"].get("polling_returned") == 2)
            require(
                snapshot()["inbox"] == snapshot()["delivered"] == 1,
                "Polling replay duplicated durable work",
            )
            compose("--profile", "polling", "stop", "poller")
            configuration(
                config,
                {
                    "JANUARY_TELEGRAM_DELIVERY_MODE": "webhook",
                    "JANUARY_TELEGRAM_WEBHOOK_PUBLIC_BASE_URL": "https://fixture.invalid",
                    "JANUARY_TELEGRAM_WEBHOOK_SECRET_TOKEN": WEBHOOK_SECRET,
                },
            )
            doctor("--profile", "webhook", "--typed")
            compose("--profile", "webhook", "up", "-d", "--wait")
            running("webhook")
            # Recreating the same backend may assign a different private IP.
            backend_id = compose("ps", "-q", "backend").strip()
            address = execute(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                    backend_id,
                ]
            ).strip()
            require(
                ipaddress.ip_address(address).is_private,
                "Webhook probe must stay private",
            )
            client.base_url = f"http://{address}:8000"
            require(
                client.get("/live").status_code
                == client.get("/ready").status_code
                == 200,
                "Webhook live/ready checks failed",
            )
            event = {
                "update_id": 7002,
                "message": {
                    "message_id": 702,
                    "date": int(time.time()),
                    "chat": {"id": 72000001, "type": "private", "first_name": "Closed"},
                    "from": {"id": 73000001, "is_bot": False, "first_name": "Closed"},
                    "text": "Closed private fixture message",
                },
            }
            route = f"/api/v1/platforms/telegram/webhook/{connection}"
            require(
                client.post(route, json=event).status_code == 401,
                "Webhook accepts missing secret",
            )
            require(
                client.post(
                    route,
                    json=event,
                    headers={"X-Telegram-Bot-Api-Secret-Token": "closed-wrong"},
                ).status_code
                == 401,
                "Webhook accepts wrong secret",
            )
            require(
                snapshot()["inbox"] == 1, "Unauthorized webhook persisted an inbox row"
            )
            accepted = client.post(
                route,
                json=event,
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
            repeated = client.post(
                route,
                json=event,
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
            require(
                accepted.status_code == repeated.status_code == 200
                and accepted.json()["duplicate"] is False
                and repeated.json()["duplicate"] is True,
                "Webhook secret/dedup contract failed",
            )
            final = wait_for(snapshot, lambda row: row["delivered"] == 2)
            require(
                all(
                    final[key] == 2
                    for key in (
                        "inbox",
                        "outbox",
                        "records",
                        "incoming",
                        "outgoing",
                        "jobs",
                        "plans",
                        "attempts",
                        "consumed",
                    )
                ),
                "Webhook durable/governed delivery flow is incomplete",
            )
            require(
                final["cursors"] == final["conversations"] == 1
                and final["cursor"] == "7002"
                and final["reserved"] == final["recoveries"] == 0,
                "Mode transition lost cursor/authority/accounting invariants",
            )
        counts = boundary()["counts"]
        require(
            counts.get("generation")
            == counts.get("sendMessage")
            == counts.get("reply_checked")
            == 2
            and counts.get("unexpected", 0) == 0,
            "Closed external boundary observed unexpected/duplicate I/O",
        )
        logs = compose("--profile", "*", "logs", "--no-color", "--tail", "500")
        require(
            all(
                value not in logs
                for value in (
                    TOKEN,
                    KEY,
                    WEBHOOK_SECRET,
                    recorded["JANUARY_DATABASE_PASSWORD"],
                    recorded["JANUARY_CONTROL_PLANE_JWT_SECRET"],
                    "Closed private fixture message",
                    "Closed fixture answer",
                )
            ),
            "Runtime leaked private configuration/content",
        )
        # Match the guide's normal bridge/loopback publication separately from
        # external-I/O containment. Stop/remove all writers first, preserve only
        # this owned PostgreSQL volume, and start the read-only-observed API plus
        # its actual DB/Redis/migration dependencies, no ingress/I/O worker.
        redis_id = compose("ps", "-q", "redis").strip()
        redis = json.loads(execute(["docker", "inspect", redis_id]))[0]
        require(
            redis["Config"]["Labels"]["com.docker.compose.project"] == project
            and redis["Config"]["Labels"]["com.docker.compose.service"] == "redis",
            "Publication handoff selected a different Redis owner",
        )
        retained_coordination_volumes = [
            mount["Name"]
            for mount in redis["Mounts"]
            if mount["Type"] == "volume" and mount["Destination"] == "/data"
        ]
        require(
            len(retained_coordination_volumes) == 1,
            "Expected exactly one owned disposable Redis data volume",
        )
        compose("--profile", "*", "down")
        # down without --volumes deliberately retains authoritative PostgreSQL,
        # but also retains Redis image-declared anonymous /data. Remove only
        # the captured, now-unreferenced coordination mount before recreating.
        remove_retained_coordination()
        override.write_text(
            override.read_text().replace("internal: true", "internal: false")
        )
        compose("--profile", "webhook", "up", "-d", "--wait", "backend")
        rows = [
            json.loads(line)
            for line in compose("ps", "--all", "--format", "json").splitlines()
            if line
        ]
        require(
            {row["Service"] for row in rows if row["State"] == "running"}
            == {"backend", "database", "redis"},
            "Publication probe unexpectedly started I/O workers",
        )
        execute(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                f"http://127.0.0.1:{port}/live",
            ]
        )
        execute(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                f"http://127.0.0.1:{port}/ready",
            ]
        )
        require(snapshot()["delivered"] == 2, "Publication/restart lost durable state")
        print(
            "Fresh self-host runtime: base-to-head, real setup/auth, all core workers, "
            "live/ready, polling cursor/restart/replay, webhook secret/dedup "
            "and 2 governed deliveries PASS; real external calls 0"
        )
    finally:
        if owned:
            compose("--profile", "*", "down", "--volumes")
            remove_retained_coordination()
            for resource in ("ps", "volume ls", "network ls"):
                command = ["docker", *resource.split()]
                if resource == "ps":
                    command.append("-a")
                command += [
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--format",
                    "{{.ID}}",
                ]
                require(
                    execute(command).strip() == "",
                    "Owned runtime proof cleanup incomplete",
                )
