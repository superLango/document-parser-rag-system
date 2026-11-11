from __future__ import annotations

import subprocess
import sys

import pytest

from services.agent.watchdog import MemoryWatchdog, WatchdogConfig, WatchdogTripped


def test_trips_below_floor() -> None:
    samples = iter([8192, 1024])
    trips: list[WatchdogTripped] = []
    watchdog = MemoryWatchdog(
        lambda: next(samples),
        WatchdogConfig(floor_mb=2048, interval_seconds=0.01),
        on_trip=trips.append,
    )
    assert watchdog.check() == 8192
    with pytest.raises(WatchdogTripped) as exc:
        watchdog.check()
    assert exc.value.available_mb == 1024
    assert exc.value.reason == "low_memory"
    assert len(trips) == 1


def test_source_error_trips_after_threshold() -> None:
    def source() -> int:
        raise RuntimeError("ssh unavailable")

    watchdog = MemoryWatchdog(
        source,
        WatchdogConfig(floor_mb=2048, max_source_errors=2),
    )
    assert watchdog.check() == -1
    with pytest.raises(WatchdogTripped) as exc:
        watchdog.check()
    assert exc.value.reason == "memory_source_error"


def test_guard_terminates_child() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    watchdog = MemoryWatchdog(
        lambda: 128,
        WatchdogConfig(floor_mb=2048, interval_seconds=0.01, grace_seconds=1.0),
    )
    try:
        with pytest.raises(WatchdogTripped):
            watchdog.guard(process)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_run_stops_after_max_samples() -> None:
    watchdog = MemoryWatchdog(
        lambda: 4096,
        WatchdogConfig(floor_mb=2048, interval_seconds=0.01),
    )
    assert watchdog.run(max_samples=3) == 4096
