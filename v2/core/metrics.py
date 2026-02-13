"""Lightweight counters and latencies for command-interpreter observability."""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class MetricsSummary:
    counters: Dict[str, int]
    latencies_ms: Dict[str, Dict[str, float]]


class _MetricsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {}
        self._latencies: Dict[str, Dict[str, float]] = {}

    def increment(self, name: str, amount: int = 1) -> None:
        if not name:
            return
        with self._lock:
            self._counters[name] = int(self._counters.get(name, 0)) + int(amount)

    def record_latency(self, name: str, value_ms: float) -> None:
        if not name:
            return
        latency_ms = max(0.0, float(value_ms))
        with self._lock:
            bucket = self._latencies.setdefault(
                name,
                {
                    "count": 0.0,
                    "total_ms": 0.0,
                    "min_ms": latency_ms,
                    "max_ms": latency_ms,
                    "avg_ms": 0.0,
                },
            )
            bucket["count"] += 1.0
            bucket["total_ms"] += latency_ms
            bucket["min_ms"] = min(float(bucket["min_ms"]), latency_ms)
            bucket["max_ms"] = max(float(bucket["max_ms"]), latency_ms)
            bucket["avg_ms"] = float(bucket["total_ms"]) / float(bucket["count"])

    def summary(self) -> MetricsSummary:
        with self._lock:
            counters = copy.deepcopy(self._counters)
            latencies = copy.deepcopy(self._latencies)
        return MetricsSummary(counters=counters, latencies_ms=latencies)

    def reset(self) -> None:
        with self._lock:
            self._counters = {}
            self._latencies = {}


_STORE = _MetricsStore()


def increment_metric(name: str, amount: int = 1) -> None:
    _STORE.increment(name, amount=amount)


def record_latency_ms(name: str, value_ms: float) -> None:
    _STORE.record_latency(name, value_ms=value_ms)


def get_metrics_summary() -> MetricsSummary:
    return _STORE.summary()


def reset_metrics() -> None:
    _STORE.reset()
