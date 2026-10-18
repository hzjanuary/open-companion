"""Configure only January logging, then run an existing worker unchanged."""

import argparse
import logging
import runpy
import sys

from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import configure_logging

WORKERS = (
    "telegram_poller",
    "ingress_outbox_dispatcher",
    "conversation_worker",
    "response_planning_worker",
    "telegram_command_worker",
    "outbound_delivery_worker",
    "provider_governance_worker",
    "governance_worker",
    "retention_worker",
    "proactive_scheduler_worker",
    "conversation_summary_worker",
    "semantic_memory_index_worker",
    "knowledge_index_worker",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker", choices=WORKERS)
    args = parser.parse_args()
    try:
        settings = Settings(_env_file=None)
    except ValidationError:
        print("Worker configuration invalid (values redacted).", file=sys.stderr)
        return 1
    # No root/httpx/httpcore INFO handlers: Telegram request URLs carry tokens.
    configure_logging(settings.log_level)
    # run_module assigns __name__='__main__'. Existing workers use that logger;
    # route it through January's formatter without enabling root/HTTP clients.
    january = logging.getLogger("january")
    worker = logging.getLogger("__main__")
    worker.setLevel(january.level)
    worker.handlers = list(january.handlers)
    worker.propagate = False
    sys.argv = [f"app.runtime.{args.worker}"]
    runpy.run_module(f"app.runtime.{args.worker}", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
