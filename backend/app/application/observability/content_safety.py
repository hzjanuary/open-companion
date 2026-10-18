"""Content-safety guard for SPEC-023 alert and incident artifacts.

This mirrors the SPEC-022 acceptance-evidence discipline
(``app.runtime.acceptance_evidence.assert_content_safe``) at the application
layer so alert and incident tooling stays inside the dependency direction
``domain <- application <- infrastructure <- interface <- runtime``. The
runtime evidence gate and this guard reject the same content and
credential-shaped classes so no alert payload, notification body, incident
record, or review document can carry product content or credentials.
"""

from __future__ import annotations

import re
from typing import Final

FORBIDDEN_ALERT_KEYS: Final = frozenset(
    {
        "authorization",
        "secret",
        "secret_token",
        "token",
        "api_key",
        "password",
        "raw_payload",
        "raw_body",
        "text",
        "message",
        "prompt",
        "provider_body",
        "memory",
        "vector",
        "content",
        "transcript",
    }
)

BOT_TOKEN_PATTERN: Final = re.compile(r"\d{6,10}:[A-Za-z0-9_-]{35}")
CREDENTIAL_PATTERNS: Final = (
    re.compile(r"(?i)\bauthorization\s*:"),
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)\bx-telegram-bot-api-secret-token\s*:"),
)
CREDENTIAL_PREFIXES: Final = ("ghp_", "sk-", "xoxb-", "AKIA")


class ContentSafetyViolation(ValueError):
    pass


def assert_content_safe(value: object, key: str = "root") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key in FORBIDDEN_ALERT_KEYS:
                raise ContentSafetyViolation(
                    f"forbidden alert key {child_key!r} under {key!r}"
                )
            assert_content_safe(child, child_key)
    elif isinstance(value, list | tuple):
        for item in value:
            assert_content_safe(item, key)
    elif isinstance(value, str):
        if BOT_TOKEN_PATTERN.search(value) or any(
            pattern.search(value) for pattern in CREDENTIAL_PATTERNS
        ):
            raise ContentSafetyViolation(f"credential-shaped string under {key!r}")
        for prefix in CREDENTIAL_PREFIXES:
            if value.startswith(prefix):
                raise ContentSafetyViolation(f"credential-shaped string under {key!r}")
