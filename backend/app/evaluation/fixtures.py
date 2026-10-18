"""Fail-closed JSON fixture loading for SPEC-032."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.evaluation.models import EvalSuite, FixtureProvenanceKind


class FixtureError(ValueError):
    """Fixture data is unsafe, malformed, or unsupported."""


_SECRET_PATTERNS = (
    re.compile(r"\b\d{6,10}:[A-Za-z0-9_-]{35}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|key)-[A-Za-z0-9_-]{24,}\b"),
)
_PROHIBITED_KEYS = {
    "telegram_token",
    "bot_token",
    "api_key",
    "authorization",
    "production_conversation",
    "raw_media",
}


def load_suite(path: Path, *, canonical: bool = True) -> EvalSuite:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise FixtureError("fixture cannot be read") from error
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise FixtureError("fixture is not valid JSON") from error
    _reject_unsafe(raw)
    try:
        suite = EvalSuite.model_validate_json(raw_text, strict=True)
    except ValidationError as error:
        raise FixtureError(_bounded_validation_error(error)) from error
    if canonical and any(
        scenario.provenance.kind != FixtureProvenanceKind.REPOSITORY_SYNTHETIC
        for scenario in suite.scenarios
    ):
        raise FixtureError("canonical fixtures must be repository synthetic")
    return suite


def _reject_unsafe(value: Any, *, key: str | None = None) -> None:
    if key is not None and key.casefold() in _PROHIBITED_KEYS:
        raise FixtureError("fixture contains a prohibited secret/content field")
    if isinstance(value, dict):
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                raise FixtureError("fixture object keys must be strings")
            _reject_unsafe(child, key=child_key)
        return
    if isinstance(value, list):
        for child in value:
            _reject_unsafe(child)
        return
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in _SECRET_PATTERNS
    ):
        raise FixtureError("fixture contains credential-shaped content")


def _bounded_validation_error(error: ValidationError) -> str:
    first = error.errors(include_url=False, include_input=False)[0]
    location = ".".join(str(item) for item in first["loc"])
    message = str(first["msg"])
    return f"invalid fixture at {location}: {message}"[:240]
