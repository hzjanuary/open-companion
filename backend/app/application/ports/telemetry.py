"""Platform-neutral operational telemetry boundary."""

from typing import Protocol


class MetricsRecorder(Protocol):
    """Record only bounded, content-free operational measurements."""

    def increment(self, metric: str, amount: float = 1.0, /, **labels: str) -> None: ...

    def observe(self, metric: str, value: float, /, **labels: str) -> None: ...

    def set_gauge(self, metric: str, value: float, /, **labels: str) -> None: ...

    def exposition(self) -> str: ...


class NoOpMetricsRecorder:
    def increment(self, metric: str, amount: float = 1.0, /, **labels: str) -> None:
        return None

    def observe(self, metric: str, value: float, /, **labels: str) -> None:
        return None

    def set_gauge(self, metric: str, value: float, /, **labels: str) -> None:
        return None

    def exposition(self) -> str:
        return ""
