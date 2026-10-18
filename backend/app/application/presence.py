"""Owned, bounded best-effort response presence feedback."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from time import monotonic

from app.application.ports.platform import PlatformAdapterError
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.domain.ambient import ParticipationTrigger
from app.domain.persistence import Platform

TELEGRAM_TYPING_REFRESH_SECONDS = 4.0
TELEGRAM_TYPING_MAX_LIFETIME_SECONDS = 20.0
TELEGRAM_TYPING_MAX_CALLS = 5

PresenceCall = Callable[[], Awaitable[None]]
PresenceFence = Callable[[], Awaitable[bool]]
Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


def telegram_typing_candidate(
    platform: Platform, trigger: ParticipationTrigger, telegram_enabled: bool
) -> bool:
    """Return whether work may construct presence before final provider admission."""

    return (
        telegram_enabled
        and platform == Platform.TELEGRAM
        and trigger == ParticipationTrigger.ADDRESSED
    )


class TypingPresenceController:
    """Own one bounded heartbeat task and serialize sends with terminal stop."""

    def __init__(
        self,
        send: PresenceCall,
        fence: PresenceFence,
        telemetry: MetricsRecorder | None = None,
        *,
        clock: Clock = monotonic,
        sleep: Sleep = asyncio.sleep,
        refresh_seconds: float = TELEGRAM_TYPING_REFRESH_SECONDS,
        max_lifetime_seconds: float = TELEGRAM_TYPING_MAX_LIFETIME_SECONDS,
        max_calls: int = TELEGRAM_TYPING_MAX_CALLS,
    ) -> None:
        if refresh_seconds <= 0 or max_lifetime_seconds <= 0 or max_calls <= 0:
            raise ValueError("presence bounds must be positive")
        self._send = send
        self._fence = fence
        self._telemetry = telemetry or NoOpMetricsRecorder()
        self._clock = clock
        self._sleep = sleep
        self._refresh_seconds = refresh_seconds
        self._max_lifetime_seconds = max_lifetime_seconds
        self._max_calls = max_calls
        self._send_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._started_at: float | None = None
        self._calls = 0
        self._stopped = False
        self._disabled = False
        self._terminal_recorded = False

    @property
    def started(self) -> bool:
        return self._started_at is not None

    @property
    def call_count(self) -> int:
        return self._calls

    async def start(self) -> None:
        """Send immediately once; subsequent calls are owned by this controller."""

        async with self._send_lock:
            if self.started or self._stopped:
                return
            self._started_at = self._clock()
            if not await self._fence():
                self._disabled = True
                self._record_terminal("authority_lost")
                return
            if not await self._send_once():
                self._record_terminal("initial_failure")
                return
            if self._calls >= self._max_calls:
                self._record_terminal("exhausted")
                return
            self._task = asyncio.create_task(
                self._refresh_loop(), name="telegram-typing-presence"
            )

    async def stop(self) -> None:
        """Idempotently prevent another send, then cancel and await owned work."""

        self._stopped = True
        task = self._task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        async with self._send_lock:
            pass
        if self.started and not self._terminal_recorded:
            self._record_terminal("stopped")

    async def _refresh_loop(self) -> None:
        while not self._inactive():
            await self._sleep(self._refresh_seconds)
            async with self._send_lock:
                if self._inactive():
                    return
                assert self._started_at is not None
                if (
                    self._calls >= self._max_calls
                    or self._clock() - self._started_at >= self._max_lifetime_seconds
                ):
                    self._record_terminal("exhausted")
                    return
                if not await self._fence():
                    self._disabled = True
                    self._record_terminal("authority_lost")
                    return
                if self._inactive() or not await self._send_once():
                    if self._disabled:
                        self._record_terminal("failure")
                    return
                if self._calls >= self._max_calls:
                    self._record_terminal("exhausted")
                    return

    def _inactive(self) -> bool:
        return self._stopped or self._disabled

    async def _send_once(self) -> bool:
        try:
            await self._send()
        except PlatformAdapterError as error:
            self._disabled = True
            self._telemetry.increment(
                "january_telegram_presence_calls_total",
                outcome="failure",
                reason=error.category.value,
            )
            return False
        self._calls += 1
        self._telemetry.increment(
            "january_telegram_presence_calls_total",
            outcome="success",
            reason="none",
        )
        return True

    def _record_terminal(self, outcome: str) -> None:
        if self._terminal_recorded:
            return
        self._terminal_recorded = True
        self._telemetry.increment(
            "january_telegram_presence_lifecycle_total", outcome=outcome
        )


PresenceControllerFactory = Callable[
    [PresenceCall, PresenceFence, MetricsRecorder], TypingPresenceController
]
