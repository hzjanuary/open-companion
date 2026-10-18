import asyncio

import pytest

from app.runtime.lifecycle import RuntimeLifecycle


def test_lifecycle_wait_returns_when_stop_is_requested() -> None:
    async def exercise() -> None:
        lifecycle = RuntimeLifecycle("test")
        waiter = asyncio.create_task(lifecycle.wait(10))
        await asyncio.sleep(0)
        lifecycle.request_stop()
        await asyncio.wait_for(waiter, timeout=1)
        assert lifecycle.stopping

    asyncio.run(exercise())


def test_safe_configuration_fingerprint_contains_no_secret_values() -> None:
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        telegram_enabled=True,
        telegram_bot_token="secret-token",
        telegram_delivery_mode="polling",
        telegram_platform_connection_id="00000000-0000-0000-0000-000000000001",
    )

    fingerprint = settings.safe_configuration_fingerprint()

    assert fingerprint["environment"] == "local"
    assert "secret-token" not in repr(fingerprint)
    assert "database_password" not in fingerprint


def test_staging_rejects_local_defaults() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="staging")


def test_staging_rejects_local_redis_when_database_defaults_are_replaced() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="redis_url"):
        Settings(
            _env_file=None,
            environment="staging",
            database_host="database",
            database_password="synthetic-staging-password",
        )
