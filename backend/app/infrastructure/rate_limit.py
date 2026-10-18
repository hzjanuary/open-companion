"""Redis-backed atomic fixed-window multi-scope rate limiter."""

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.application.ports.rate_limit import RateLimiter
from app.core.config import Settings
from app.domain.rate_limit import (
    RateLimitDecision,
    RateLimitOperation,
    RateLimitRule,
)

_CHECK_ALL = """
local now = redis.call('TIME')
for index, key in ipairs(KEYS) do
  local limit = tonumber(ARGV[(index - 1) * 2 + 1])
  local window = tonumber(ARGV[(index - 1) * 2 + 2])
  local value = tonumber(redis.call('GET', key) or '0')
  if value >= limit then
    local ttl = tonumber(redis.call('TTL', key) or window)
    if ttl < 1 then ttl = 1 end
    return {0, index, ttl}
  end
end
for index, key in ipairs(KEYS) do
  local window = tonumber(ARGV[(index - 1) * 2 + 2])
  local value = redis.call('INCR', key)
  if value == 1 then redis.call('EXPIRE', key, window) end
end
return {1, 0, 0}
"""


class RateLimitUnavailable(RuntimeError):
    """Enabled coordination could not reach Redis and must fail closed."""


class RedisRateLimiter(RateLimiter):
    def __init__(self, settings: Settings, client: Redis | None = None) -> None:
        self._owned_client = client is None
        self._client = client or Redis.from_url(
            settings.redis_url.get_secret_value(), decode_responses=False
        )

    async def check(
        self, operation: RateLimitOperation, rules: tuple[RateLimitRule, ...]
    ) -> RateLimitDecision:
        if not rules:
            return RateLimitDecision(True)
        keys = [
            f"january:rate-limit:{operation.value}:{rule.scope.value}:{rule.identifier}"
            for rule in rules
        ]
        args: list[str] = []
        for rule in rules:
            args.extend((str(rule.limit), str(rule.window_seconds)))
        try:
            result = await self._client.execute_command(
                "EVAL", _CHECK_ALL, len(keys), *keys, *args
            )
        except RedisError as error:
            raise RateLimitUnavailable(
                "Redis rate-limit coordination unavailable"
            ) from error
        if not isinstance(result, list) or len(result) != 3:
            raise RateLimitUnavailable("Redis rate-limit response was malformed")
        if int(result[0]) == 1:
            return RateLimitDecision(True)
        index = int(result[1]) - 1
        return RateLimitDecision(False, rules[index].scope, max(1, int(result[2])))

    async def is_ready(self) -> bool:
        try:
            return bool(await self._client.ping())
        except RedisError:
            return False

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()
