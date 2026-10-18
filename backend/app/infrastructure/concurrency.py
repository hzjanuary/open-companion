"""Redis-backed, content-free provider concurrency leases."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from redis.asyncio import Redis

from app.application.ports.concurrency import ConcurrencyLease, ConcurrencyLimiter
from app.core.config import Settings
from app.domain.planning import ProviderId


class ConcurrencyUnavailable(RuntimeError):
    """Redis cannot safely coordinate provider capacity."""


@dataclass(frozen=True)
class ProviderLease:
    provider: ProviderId
    token: str


class InMemoryConcurrencyLimiter(ConcurrencyLimiter):
    """Deterministic fake for tests; expiry is evaluated against injected clock."""

    def __init__(
        self,
        limits: dict[str, int],
        lease_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits, self._lease_seconds, self._clock = limits, lease_seconds, clock
        self._leases: dict[str, tuple[ProviderId, float]] = {}

    def _expire(self) -> None:
        now = self._clock()
        self._leases = {k: v for k, v in self._leases.items() if v[1] > now}

    async def acquire(self, provider: ProviderId) -> ConcurrencyLease | None:
        self._expire()
        if sum(
            1 for value in self._leases.values() if value[0] == provider
        ) >= self._limits.get(provider.value, 1):
            return None
        token = uuid4().hex
        self._leases[token] = (provider, self._clock() + self._lease_seconds)
        return ProviderLease(provider, token)

    async def release(self, lease: ConcurrencyLease) -> None:
        self._leases.pop(lease.token, None)

    async def is_ready(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class RedisConcurrencyLimiter(ConcurrencyLimiter):
    """A sorted-set semaphore. Tokens are opaque and keys never contain content."""

    _ACQUIRE = """
local key, limit, now, ttl, token = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]),
  tonumber(ARGV[3]), ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - ttl)
if redis.call('ZCARD', key) >= limit then return 0 end
redis.call('ZADD', key, now, token)
redis.call('PEXPIRE', key, ttl)
return 1
"""
    _RELEASE = "return redis.call('ZREM', KEYS[1], ARGV[1])"

    def __init__(self, settings: Settings) -> None:
        self._redis = Redis.from_url(
            settings.redis_url.get_secret_value(), decode_responses=True
        )
        self._limits = settings.provider_concurrency_limits
        self._ttl_ms = settings.provider_concurrency_lease_seconds * 1000

    def _key(self, provider: ProviderId) -> str:
        return f"january:provider-concurrency:{provider.value}"

    async def acquire(self, provider: ProviderId) -> ConcurrencyLease | None:
        token = uuid4().hex
        try:
            acquired = await self._redis.eval(
                self._ACQUIRE,
                1,
                self._key(provider),
                self._limits.get(provider.value, 1),
                int(time.time() * 1000),
                self._ttl_ms,
                token,
            )
        except Exception as exc:  # redis client errors are intentionally fail-closed
            raise ConcurrencyUnavailable(
                "provider concurrency coordination unavailable"
            ) from exc
        return ProviderLease(provider, token) if acquired else None

    async def release(self, lease: ConcurrencyLease) -> None:
        try:
            await self._redis.eval(
                self._RELEASE, 1, self._key(lease.provider), lease.token
            )
        except Exception as exc:
            raise ConcurrencyUnavailable(
                "provider concurrency release unavailable"
            ) from exc

    async def is_ready(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._redis.aclose()
