"""Lightweight Prometheus-style metrics with no third-party dependencies.

Counters/gauges/histogram summaries are process-local; each service instance
exposes them at ``/metrics`` so Prometheus can scrape per-pod values.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager

__version__ = "0.1.0"

_LOCK = threading.Lock()
_COUNTERS: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_GAUGES: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_HISTOGRAMS: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(list)
HISTOGRAM_LIMIT = 4096


def _labels(**labels: object) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def inc(name: str, value: float = 1.0, **labels: object) -> None:
    key = (name, _labels(**labels))
    with _LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0.0) + float(value)


def set_gauge(name: str, value: float, **labels: object) -> None:
    key = (name, _labels(**labels))
    with _LOCK:
        _GAUGES[key] = float(value)


def observe(name: str, value: float, **labels: object) -> None:
    key = (name, _labels(**labels))
    with _LOCK:
        samples = _HISTOGRAMS[key]
        samples.append(float(value))
        if len(samples) > HISTOGRAM_LIMIT:
            del samples[: len(samples) - HISTOGRAM_LIMIT]


@contextmanager
def timer(name: str, **labels: object) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        observe(name, time.perf_counter() - started, **labels)


def reset() -> None:
    with _LOCK:
        _COUNTERS.clear()
        _GAUGES.clear()
        _HISTOGRAMS.clear()


def _render_key(name: str, labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return name
    rendered = ",".join(f'{key}="{value}"' for key, value in labels)
    return f"{name}{{{rendered}}}"


def render_prometheus() -> str:
    lines: list[str] = []
    with _LOCK:
        counters = dict(_COUNTERS)
        gauges = dict(_GAUGES)
        histograms = {key: list(value) for key, value in _HISTOGRAMS.items()}
    for (name, labels), value in sorted(counters.items()):
        lines.append(f"{_render_key(name, labels)} {value:g}")
    for (name, labels), value in sorted(gauges.items()):
        lines.append(f"{_render_key(name, labels)} {value:g}")
    for (name, labels), samples in sorted(histograms.items()):
        if not samples:
            continue
        lines.append(f"{_render_key(name + '_count', labels)} {len(samples)}")
        lines.append(f"{_render_key(name + '_sum', labels)} {sum(samples):g}")
    return "\n".join(lines) + ("\n" if lines else "")
