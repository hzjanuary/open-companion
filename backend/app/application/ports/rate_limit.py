"""Application port for all-process coordination without content-bearing keys."""

from typing import Protocol

from app.domain.rate_limit import RateLimitDecision, RateLimitOperation, RateLimitRule


class RateLimiter(Protocol):
    async def check(
        self, operation: RateLimitOperation, rules: tuple[RateLimitRule, ...]
    ) -> RateLimitDecision: ...

    async def is_ready(self) -> bool: ...

    async def aclose(self) -> None: ...
