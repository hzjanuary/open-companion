"""Deterministic task-ownership and timing proof for Telegram presence."""

import asyncio

import pytest

from app.application.ports.platform import PlatformAdapterError, PlatformErrorCategory
from app.application.presence import TypingPresenceController, telegram_typing_candidate
from app.domain.ambient import ParticipationTrigger
from app.domain.persistence import Platform
from app.infrastructure.telemetry import InMemoryMetricsRecorder


class ControlledTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.waiters: list[asyncio.Future[None]] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        assert seconds == 4.0
        waiter = asyncio.get_running_loop().create_future()
        self.waiters.append(waiter)
        await waiter

    async def advance(self, seconds: float = 4.0) -> None:
        while not self.waiters:
            await asyncio.sleep(0)
        self.now += seconds
        self.waiters.pop(0).set_result(None)
        await asyncio.sleep(0)


@pytest.mark.parametrize(
    ("platform", "trigger", "enabled", "expected"),
    [
        (Platform.TELEGRAM, ParticipationTrigger.ADDRESSED, True, True),
        (Platform.TELEGRAM, ParticipationTrigger.AMBIENT, True, False),
        (Platform.TELEGRAM, ParticipationTrigger.COMMAND, True, False),
        (Platform.TELEGRAM, ParticipationTrigger.SCHEDULED, True, False),
        (Platform.TELEGRAM, ParticipationTrigger.ADDRESSED, False, False),
        (Platform.ZALO, ParticipationTrigger.ADDRESSED, True, False),
    ],
)
def test_presence_candidate_is_exact(
    platform: Platform,
    trigger: ParticipationTrigger,
    enabled: bool,
    expected: bool,
) -> None:
    assert telegram_typing_candidate(platform, trigger, enabled) is expected


def test_presence_starts_immediately_refreshes_and_stops_at_five_calls() -> None:
    async def scenario() -> None:
        timeline = ControlledTime()
        sends: list[float] = []
        fences = 0
        metrics = InMemoryMetricsRecorder()

        async def send() -> None:
            sends.append(timeline.now)

        async def fence() -> bool:
            nonlocal fences
            fences += 1
            return True

        controller = TypingPresenceController(
            send, fence, metrics, clock=timeline.clock, sleep=timeline.sleep
        )
        await controller.start()
        assert sends == [0.0]
        for _ in range(4):
            await timeline.advance()
        assert sends == [0.0, 4.0, 8.0, 12.0, 16.0]
        assert fences == 5
        assert controller.call_count == 5
        assert (
            metrics.counter_value(
                "january_telegram_presence_lifecycle_total", outcome="exhausted"
            )
            == 1
        )
        await controller.stop()
        assert not any(
            task.get_name() == "telegram-typing-presence" and not task.done()
            for task in asyncio.all_tasks()
        )

    asyncio.run(scenario())


def test_presence_stops_at_lifetime_before_late_send() -> None:
    async def scenario() -> None:
        timeline = ControlledTime()
        sends = 0

        async def send() -> None:
            nonlocal sends
            sends += 1

        async def fence() -> bool:
            return True

        controller = TypingPresenceController(
            send,
            fence,
            clock=timeline.clock,
            sleep=timeline.sleep,
            max_lifetime_seconds=4.0,
            max_calls=10,
        )
        await controller.start()
        await timeline.advance()
        assert sends == 1
        await controller.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_at", [1, 2])
def test_first_adapter_failure_disables_all_future_calls(failure_at: int) -> None:
    async def scenario() -> None:
        timeline = ControlledTime()
        attempts = 0
        metrics = InMemoryMetricsRecorder()

        async def send() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == failure_at:
                raise PlatformAdapterError(
                    PlatformErrorCategory.RATE_LIMITED, "sendChatAction"
                )

        async def fence() -> bool:
            return True

        controller = TypingPresenceController(
            send, fence, metrics, clock=timeline.clock, sleep=timeline.sleep
        )
        await controller.start()
        if failure_at == 2:
            await timeline.advance()
        await controller.stop()
        assert attempts == failure_at
        assert (
            metrics.counter_value(
                "january_telegram_presence_calls_total",
                outcome="failure",
                reason="rate_limited",
            )
            == 1
        )
        expected = "initial_failure" if failure_at == 1 else "failure"
        assert (
            metrics.counter_value(
                "january_telegram_presence_lifecycle_total", outcome=expected
            )
            == 1
        )
        assert not any(
            task.get_name() == "telegram-typing-presence" and not task.done()
            for task in asyncio.all_tasks()
        )

    asyncio.run(scenario())


def test_failed_fence_stops_without_another_send() -> None:
    async def scenario() -> None:
        timeline = ControlledTime()
        sends = 0
        metrics = InMemoryMetricsRecorder()

        async def send() -> None:
            nonlocal sends
            sends += 1

        async def fence() -> bool:
            return False

        controller = TypingPresenceController(
            send, fence, metrics, clock=timeline.clock, sleep=timeline.sleep
        )
        await controller.start()
        await controller.stop()
        assert sends == 0
        assert (
            metrics.counter_value(
                "january_telegram_presence_lifecycle_total", outcome="authority_lost"
            )
            == 1
        )

    asyncio.run(scenario())


def test_stop_cancels_inflight_refresh_and_is_idempotent() -> None:
    async def scenario() -> None:
        timeline = ControlledTime()
        refresh_started = asyncio.Event()
        attempts = 0

        async def send() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                refresh_started.set()
                await asyncio.Event().wait()

        async def fence() -> bool:
            return True

        controller = TypingPresenceController(
            send, fence, clock=timeline.clock, sleep=timeline.sleep
        )
        await controller.start()
        await timeline.advance()
        await refresh_started.wait()
        await controller.stop()
        await controller.stop()
        assert attempts == 2
        assert not any(
            task.get_name() == "telegram-typing-presence" and not task.done()
            for task in asyncio.all_tasks()
        )

    asyncio.run(scenario())


def test_concurrent_start_owns_only_one_loop() -> None:
    async def scenario() -> None:
        timeline = ControlledTime()
        sends = 0

        async def send() -> None:
            nonlocal sends
            sends += 1

        async def fence() -> bool:
            return True

        controller = TypingPresenceController(
            send, fence, clock=timeline.clock, sleep=timeline.sleep
        )
        await asyncio.gather(controller.start(), controller.start())
        await controller.stop()
        assert sends == 1
        assert not any(
            task.get_name() == "telegram-typing-presence" and not task.done()
            for task in asyncio.all_tasks()
        )

    asyncio.run(scenario())


def test_stop_before_refresh_boundary_prevents_late_call() -> None:
    async def scenario() -> None:
        timeline = ControlledTime()
        sends = 0

        async def send() -> None:
            nonlocal sends
            sends += 1

        async def fence() -> bool:
            return True

        controller = TypingPresenceController(
            send, fence, clock=timeline.clock, sleep=timeline.sleep
        )
        await controller.start()
        while not timeline.waiters:
            await asyncio.sleep(0)
        await controller.stop()
        await asyncio.sleep(0)
        assert sends == 1
        assert all(waiter.cancelled() for waiter in timeline.waiters)

    asyncio.run(scenario())


def test_programmer_error_is_not_hidden() -> None:
    async def broken_send() -> None:
        raise RuntimeError("programmer defect")

    async def fence() -> bool:
        return True

    with pytest.raises(RuntimeError, match="programmer defect"):
        asyncio.run(TypingPresenceController(broken_send, fence).start())
