"""Offline CLI for the SPEC-032 conversation quality suite."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.evaluation.fixtures import FixtureError, load_suite
from app.evaluation.models import EvalCategory, EvalStatus
from app.evaluation.reporting import render_json, render_terminal
from app.evaluation.runner import EvalSelection, SelectionError, run_suite

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE = PROJECT_ROOT / "evals/fixtures/telegram-core-v1.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic offline AI conversation evaluations."
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--category", choices=[item.value for item in EvalCategory])
    parser.add_argument("--scenario")
    parser.add_argument("--json", metavar="PATH_OR_DASH")
    parser.add_argument("--judge", choices=["disabled"], default="disabled")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        suite = load_suite(args.fixture)
        selection = EvalSelection(
            category=EvalCategory(args.category) if args.category else None,
            scenario_id=args.scenario,
        )
        run = asyncio.run(run_suite(suite, selection=selection))
    except (FixtureError, SelectionError) as error:
        print(f"ai-eval configuration error: {error}", file=sys.stderr)
        return 2
    machine = render_json(run)
    if args.json == "-":
        sys.stdout.write(machine)
    else:
        sys.stdout.write(render_terminal(run))
        if args.json:
            try:
                Path(args.json).write_text(machine, encoding="utf-8")
            except OSError:
                print("ai-eval report could not be written", file=sys.stderr)
                return 2
    return 0 if run.status == EvalStatus.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
