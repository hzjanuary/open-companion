"""Shared signal, drain, and content-safe lifecycle handling for workers."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Iterable

logger = logging.getLogger("january.runtime")


class RuntimeLifecycle:
    """Coordinate bounded worker draining without owning business state."""

    def __init__(self, runtime: str, signals: Iterable[signal.Signals] | None = None):
        self.runtime = runtime
        self._stopped = asyncio.Event()
        self._signals = tuple(signals or (signal.SIGINT, signal.SIGTERM))
        self._installed: list[signal.Signals] = []

    @property
    def stopping(self) -> bool:
        return self._stopped.is_set()

    def request_stop(self) -> None:
        if not self._stopped.is_set():
            self._stopped.set()
            logger.info("runtime_draining", extra={"runtime": self.runtime})

    def install(self) -> None:
        loop = asyncio.get_running_loop()
        for signum in self._signals:
            try:
                loop.add_signal_handler(signum, self.request_stop)
                self._installed.append(signum)
            except (NotImplementedError, RuntimeError, ValueError):
                logger.debug(
                    "runtime_signal_handler_unavailable",
                    extra={"runtime": self.runtime, "signal": signum.name},
                )
        logger.info("runtime_started", extra={"runtime": self.runtime})

    def close(self) -> None:
        loop = asyncio.get_running_loop()
        for signum in self._installed:
            try:
                loop.remove_signal_handler(signum)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
        self._installed.clear()
        logger.info("runtime_stopped", extra={"runtime": self.runtime})

    async def wait(self, seconds: float) -> None:
        """Wait for drain or the next poll interval, whichever comes first."""

        if self.stopping:
            return
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=seconds)
        except TimeoutError:
            return
