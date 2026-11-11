"""Memory watchdog for model-server tests.

The watchdog never kills the model service during a test; it aborts the test
client when the model host's available memory falls below the configured floor.
For model *startup* it can instead terminate the model process that was just
started, so a failed load cannot exhaust the host.

The module is dependency-free and clock/sleep injectable so it can be tested
without a real model server.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class WatchdogTripped(RuntimeError):
    def __init__(
        self,
        available_mb: int | None,
        floor_mb: int,
        reason: str = "low_memory",
        detail: str = "",
    ) -> None:
        self.available_mb = available_mb
        self.floor_mb = floor_mb
        self.reason = reason
        self.detail = detail
        available = "unknown" if available_mb is None else f"{available_mb}MiB"
        message = f"watchdog tripped: {reason} available={available} floor={floor_mb}MiB"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


@dataclass(frozen=True)
class WatchdogConfig:
    floor_mb: int = 2048
    interval_seconds: float = 2.0
    grace_seconds: float = 3.0
    max_source_errors: int = 3


class MemoryWatchdog:
    def __init__(
        self,
        available_mb: Callable[[], int],
        config: WatchdogConfig | None = None,
        on_trip: Callable[[WatchdogTripped], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._available_mb = available_mb
        self.config = config or WatchdogConfig()
        self._on_trip = on_trip
        self._sleep = sleep
        self._source_errors = 0

    def check(self) -> int:
        try:
            available = int(self._available_mb())
        except Exception as exc:  # noqa: BLE001 - source failures must be conservative
            self._source_errors += 1
            if self._source_errors >= self.config.max_source_errors:
                error = WatchdogTripped(
                    None,
                    self.config.floor_mb,
                    reason="memory_source_error",
                    detail=str(exc),
                )
                self._trip(error)
                raise error from exc
            logger.warning(
                "watchdog memory source failed (%s/%s): %s",
                self._source_errors,
                self.config.max_source_errors,
                exc,
            )
            return -1
        self._source_errors = 0
        if available < self.config.floor_mb:
            error = WatchdogTripped(available, self.config.floor_mb)
            self._trip(error)
            raise error
        return available

    def _trip(self, error: WatchdogTripped) -> None:
        if self._on_trip is None:
            return
        try:
            self._on_trip(error)
        except Exception:  # noqa: BLE001 - never mask the trip
            logger.exception("watchdog on_trip handler failed")

    def run(
        self,
        stop_event: threading.Event | None = None,
        max_samples: int = 0,
    ) -> int | None:
        samples = 0
        last: int | None = None
        while stop_event is None or not stop_event.is_set():
            last = self.check()
            samples += 1
            if max_samples and samples >= max_samples:
                return last
            self._sleep(self.config.interval_seconds)
        return last

    def guard(self, process: subprocess.Popen, stop_event: threading.Event | None = None) -> int:
        """Monitor a child process; terminate it if the watchdog trips."""
        while process.poll() is None:
            if stop_event is not None and stop_event.is_set():
                return process.returncode or 0
            try:
                self.check()
            except WatchdogTripped:
                self.terminate(process)
                raise
            self._sleep(self.config.interval_seconds)
        return int(process.returncode or 0)

    def terminate(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=self.config.grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=self.config.grace_seconds)
