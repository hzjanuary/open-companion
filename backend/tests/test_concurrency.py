import asyncio
from typing import cast

import pytest

from app.application.model_provider import GenerationRequest
from app.application.ports.concurrency import ConcurrencyLease
from app.domain.planning import ProviderErrorCategory, ProviderId
from app.infrastructure.concurrency import (
    ConcurrencyUnavailable,
    InMemoryConcurrencyLimiter,
    ProviderLease,
)
from app.infrastructure.concurrency_provider import ConcurrencyLimitedProvider


def test_in_memory_provider_concurrency_is_owned_and_recovers_after_ttl() -> None:
    now = [0.0]

    async def scenario() -> None:
        limiter = InMemoryConcurrencyLimiter({"openai": 1}, 5, lambda: now[0])
        first = await limiter.acquire(ProviderId.OPENAI)
        assert first is not None
        assert await limiter.acquire(ProviderId.OPENAI) is None
        await limiter.release(first)
        assert await limiter.acquire(ProviderId.OPENAI) is not None
        now[0] = 6.0
        assert await limiter.acquire(ProviderId.OPENAI) is not None

    asyncio.run(scenario())


def test_provider_concurrency_unavailable_fails_closed_before_provider_io() -> None:
    class UnavailableLimiter:
        async def acquire(self, provider: ProviderId) -> ConcurrencyLease | None:
            raise ConcurrencyUnavailable("synthetic")

        async def release(self, lease: ConcurrencyLease) -> None:
            raise AssertionError("no lease was acquired")

        async def is_ready(self) -> bool:
            return False

        async def aclose(self) -> None:
            return None

    class Provider:
        provider_id = ProviderId.OPENAI
        model = "synthetic"
        capabilities = None

        async def generate(self, request: object) -> object:
            raise AssertionError("provider I/O must not run")

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        provider = ConcurrencyLimitedProvider(Provider(), UnavailableLimiter())  # type: ignore[arg-type]
        with pytest.raises(Exception) as error:
            await provider.generate(cast(GenerationRequest, object()))
        assert (
            getattr(error.value, "category", None)
            == ProviderErrorCategory.CONCURRENCY_LIMITED
        )
        assert getattr(error.value, "retryable", None) is True

    asyncio.run(scenario())


def test_provider_concurrency_resumes_after_coordination_restores() -> None:
    class RestoringLimiter:
        def __init__(self) -> None:
            self.available = False
            self.released: list[ConcurrencyLease] = []

        async def acquire(self, provider: ProviderId) -> ConcurrencyLease | None:
            if not self.available:
                raise ConcurrencyUnavailable("synthetic")
            return ProviderLease(provider, "owned")

        async def release(self, lease: ConcurrencyLease) -> None:
            self.released.append(lease)

        async def is_ready(self) -> bool:
            return self.available

        async def aclose(self) -> None:
            return None

    class Provider:
        provider_id = ProviderId.OPENAI
        model = "synthetic"
        capabilities = None

        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, request: object) -> object:
            self.calls += 1
            return object()

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        limiter = RestoringLimiter()
        delegate = Provider()
        provider = ConcurrencyLimitedProvider(delegate, limiter)  # type: ignore[arg-type]
        with pytest.raises(Exception) as error:
            await provider.generate(cast(GenerationRequest, object()))
        assert (
            getattr(error.value, "category", None)
            == ProviderErrorCategory.CONCURRENCY_LIMITED
        )
        assert delegate.calls == 0
        limiter.available = True
        await provider.generate(cast(GenerationRequest, object()))
        assert delegate.calls == 1
        assert len(limiter.released) == 1

    asyncio.run(scenario())
