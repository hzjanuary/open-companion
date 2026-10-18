"""Provider decorator that acquires distributed capacity only around I/O."""

from app.application.model_provider import (
    GenerationRequest,
    ModelProvider,
    ProviderError,
    ProviderResult,
)
from app.application.ports.concurrency import ConcurrencyLimiter
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.domain.planning import ProviderErrorCategory
from app.infrastructure.concurrency import ConcurrencyUnavailable


class ConcurrencyLimitedProvider:
    def __init__(
        self,
        provider: ModelProvider,
        limiter: ConcurrencyLimiter,
        telemetry: MetricsRecorder | None = None,
    ) -> None:
        self._provider, self._limiter = provider, limiter
        self._telemetry = telemetry or NoOpMetricsRecorder()
        self.provider_id, self.model, self.capabilities = (
            provider.provider_id,
            provider.model,
            provider.capabilities,
        )

    async def generate(self, request: GenerationRequest) -> ProviderResult:
        try:
            lease = await self._limiter.acquire(self.provider_id)
        except ConcurrencyUnavailable as exc:
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id.value,
                outcome="unavailable",
            )
            raise ProviderError(
                ProviderErrorCategory.CONCURRENCY_LIMITED,
                self.provider_id,
                self.model,
                True,
                "generate",
                "provider concurrency coordination unavailable",
            ) from exc
        if lease is None:
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id.value,
                outcome="denied",
            )
            raise ProviderError(
                ProviderErrorCategory.CONCURRENCY_LIMITED,
                self.provider_id,
                self.model,
                True,
                "generate",
                "provider concurrency capacity unavailable",
            )
        try:
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id.value,
                outcome="acquired",
            )
            return await self._provider.generate(request)
        finally:
            await self._limiter.release(lease)
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id.value,
                outcome="released",
            )

    async def aclose(self) -> None:
        await self._provider.aclose()
