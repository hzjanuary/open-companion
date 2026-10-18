"""Deterministic no-network rate limiter suitable for unit tests only."""

from collections import defaultdict
from collections.abc import Callable
from time import monotonic

from app.domain.rate_limit import RateLimitDecision, RateLimitOperation, RateLimitRule


class InMemoryRateLimiter:
    """Atomic within one process; production uses RedisRateLimiter instead."""

    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._events: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    async def check(
        self, operation: RateLimitOperation, rules: tuple[RateLimitRule, ...]
    ) -> RateLimitDecision:
        now = self._clock()
        keys = [(operation.value, rule.scope.value, rule.identifier) for rule in rules]
        active: list[list[float]] = []
        for key, rule in zip(keys, rules, strict=True):
            values = [
                point
                for point in self._events[key]
                if point > now - rule.window_seconds
            ]
            self._events[key] = values
            active.append(values)
        for rule, values in zip(rules, active, strict=True):
            if len(values) >= rule.limit:
                retry = max(1, int(values[0] + rule.window_seconds - now + 0.999))
                return RateLimitDecision(False, rule.scope, retry)
        for values in active:
            values.append(now)
        return RateLimitDecision(True)

    async def is_ready(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None
