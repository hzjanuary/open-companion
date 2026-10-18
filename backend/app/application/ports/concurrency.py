"""Port for bounded cross-process provider in-flight coordination."""

from typing import Protocol

from app.domain.planning import ProviderId


class ConcurrencyLease(Protocol):
    @property
    def provider(self) -> ProviderId: ...

    @property
    def token(self) -> str: ...


class ConcurrencyLimiter(Protocol):
    async def acquire(self, provider: ProviderId) -> ConcurrencyLease | None: ...

    async def release(self, lease: ConcurrencyLease) -> None: ...

    async def is_ready(self) -> bool: ...

    async def aclose(self) -> None: ...
