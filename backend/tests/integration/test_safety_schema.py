"""PostgreSQL and Redis proof for content-free SPEC-012 primitives."""

import asyncio

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text

from app.core.config import Settings
from app.domain.rate_limit import RateLimitOperation, RateLimitRule, RateLimitScope
from app.infrastructure.database.database import Database
from app.infrastructure.rate_limit import RateLimitUnavailable, RedisRateLimiter


@pytest.mark.integration
@pytest.mark.safety_integration
def test_safety_schema_and_redis_limiter_are_atomic_and_content_free() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        redis = Redis.from_url(
            settings.redis_url.get_secret_value(), decode_responses=True
        )
        await database.start()
        try:
            async with database.engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == "0026_conversation_feedback"
                )
                tables = set(
                    await connection.scalars(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_name IN "
                            "('safety_policy_decisions', 'rate_limit_events')"
                        )
                    )
                )
                assert tables == {"safety_policy_decisions", "rate_limit_events"}
            await redis.flushdb()
            limiter = RedisRateLimiter(settings, redis)
            rules = (
                RateLimitRule(RateLimitScope.DEPLOYMENT, "deployment", 10, 1),
                RateLimitRule(
                    RateLimitScope.CONVERSATION, "internal-conversation", 1, 1
                ),
            )
            outcomes = await asyncio.gather(
                *(limiter.check(RateLimitOperation.GENERATION, rules) for _ in range(4))
            )
            assert sum(outcome.allowed for outcome in outcomes) == 1
            denied = next(outcome for outcome in outcomes if not outcome.allowed)
            assert denied.limiting_scope == RateLimitScope.CONVERSATION
            assert denied.retry_after_seconds is not None
            keys = await redis.keys("january:rate-limit:*")
            assert keys
            assert all("fixture-content" not in key for key in keys)
            values = await asyncio.gather(*(redis.get(key) for key in keys))
            assert all(value is not None and value.isdigit() for value in values)
            await asyncio.sleep(1.1)
            assert (await limiter.check(RateLimitOperation.GENERATION, rules)).allowed

            for scope in (
                RateLimitScope.PARTICIPANT,
                RateLimitScope.CONNECTION,
                RateLimitScope.DEPLOYMENT,
                RateLimitScope.PROVIDER,
            ):
                rule = RateLimitRule(scope, f"internal-{scope.value}", 1, 10)
                assert (
                    await limiter.check(RateLimitOperation.GENERATION, (rule,))
                ).allowed
                denied = await limiter.check(RateLimitOperation.GENERATION, (rule,))
                assert denied.limiting_scope == scope

            delivery_rule = RateLimitRule(
                RateLimitScope.CONVERSATION, "internal-delivery", 1, 10
            )
            assert (
                await limiter.check(RateLimitOperation.DELIVERY, (delivery_rule,))
            ).allowed
            assert (
                await limiter.check(RateLimitOperation.DELIVERY, (delivery_rule,))
            ).limiting_scope == RateLimitScope.CONVERSATION
        finally:
            await redis.aclose()
            await database.stop()

    asyncio.run(scenario())


def test_redis_limiter_outage_fails_closed() -> None:
    class UnavailableRedis:
        async def execute_command(self, *_: object) -> object:
            raise RedisConnectionError("synthetic unavailable")

    async def scenario() -> None:
        limiter = RedisRateLimiter(Settings(_env_file=None), UnavailableRedis())  # type: ignore[arg-type]
        with pytest.raises(RateLimitUnavailable):
            await limiter.check(
                RateLimitOperation.GENERATION,
                (RateLimitRule(RateLimitScope.DEPLOYMENT, "deployment", 1, 1),),
            )

    asyncio.run(scenario())
