"""Redis-backed provider capacity is shared by independently composed workers."""

import asyncio

import pytest

from app.core.config import Settings
from app.domain.planning import ProviderId
from app.infrastructure.concurrency import RedisConcurrencyLimiter


@pytest.mark.safety_integration
@pytest.mark.integration
def test_redis_provider_concurrency_is_shared_and_release_is_owned() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            provider_concurrency_enabled=True,
            provider_concurrency_limits={"openai": 1},
        )
        first = RedisConcurrencyLimiter(settings)
        second = RedisConcurrencyLimiter(settings)
        try:
            await first._redis.delete(first._key(ProviderId.OPENAI))  # type: ignore[attr-defined]
            lease = await first.acquire(ProviderId.OPENAI)
            assert lease is not None
            assert await second.acquire(ProviderId.OPENAI) is None
            await second.release(lease)
            replacement = await first.acquire(ProviderId.OPENAI)
            assert replacement is not None
            await first.release(replacement)
            await first._redis.zadd(  # type: ignore[attr-defined]
                first._key(ProviderId.OPENAI), {"crashed-worker-token": 0}
            )
            assert await second.acquire(ProviderId.OPENAI) is not None
        finally:
            await first._redis.delete(first._key(ProviderId.OPENAI))  # type: ignore[attr-defined]
            await first.aclose()
            await second.aclose()

    asyncio.run(scenario())
