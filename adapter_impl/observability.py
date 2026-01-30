"""
Observability utilities for Billy and Agent Zero integration.

This module defines counters and histograms to record tool execution
statistics, queue depths and agent latency.  It attempts to use the
``prometheus_client`` library if available; otherwise it falls back to
lightweight in‑memory counters.  Applications can import the
``register_tool_run`` and ``get_metrics`` functions to record and
retrieve metrics.  For full observability, integrate these metrics
with your preferred monitoring stack (e.g. Prometheus, OpenTelemetry).
"""
from __future__ import annotations

import threading
import time
from typing import Dict

try:
    from prometheus_client import Counter, Histogram

    # Prometheus metrics definitions
    TOOL_RUNS_TOTAL = Counter(
        "tool_runs_total",
        "Total number of tool executions",
        ["tool", "status"],
    )
    TOOL_RUN_DURATION_SECONDS = Histogram(
        "tool_run_duration_seconds",
        "Duration of tool executions",
        ["tool"],
    )
    TOOL_QUEUE_DEPTH = Histogram(
        "tool_queue_depth", "Depth of the tool execution queue", ["queue"]
    )
    DOCKER_RUNNER_FAILURES_TOTAL = Counter(
        "docker_runner_failures_total",
        "Number of Docker runner failures", ["reason"],
    )
    AGENT_TURN_LATENCY_SECONDS = Histogram(
        "agent_turn_latency_seconds",
        "Latency per agent turn",
    )

    def register_tool_run(tool: str, status: str, duration: float) -> None:
        TOOL_RUNS_TOTAL.labels(tool=tool, status=status).inc()
        TOOL_RUN_DURATION_SECONDS.labels(tool=tool).observe(duration)

    def record_queue_depth(depth: int) -> None:
        TOOL_QUEUE_DEPTH.labels(queue="default").observe(depth)

    def record_docker_failure(reason: str) -> None:
        DOCKER_RUNNER_FAILURES_TOTAL.labels(reason=reason).inc()

    def record_agent_latency(latency: float) -> None:
        AGENT_TURN_LATENCY_SECONDS.observe(latency)

except ImportError:
    # Fallback simple counters if prometheus_client is unavailable
    _metrics_lock = threading.Lock()
    _tool_runs: Dict[str, int] = {}
    _tool_durations: Dict[str, float] = {}
    _queue_depths: list[int] = []
    _docker_failures: Dict[str, int] = {}
    _agent_latencies: list[float] = []

    def register_tool_run(tool: str, status: str, duration: float) -> None:
        key = f"{tool}:{status}"
        with _metrics_lock:
            _tool_runs[key] = _tool_runs.get(key, 0) + 1
            _tool_durations[tool] = _tool_durations.get(tool, 0.0) + duration

    def record_queue_depth(depth: int) -> None:
        with _metrics_lock:
            _queue_depths.append(depth)

    def record_docker_failure(reason: str) -> None:
        with _metrics_lock:
            _docker_failures[reason] = _docker_failures.get(reason, 0) + 1

    def record_agent_latency(latency: float) -> None:
        with _metrics_lock:
            _agent_latencies.append(latency)

    def get_metrics() -> Dict[str, any]:
        """Return a snapshot of collected metrics for inspection or testing."""
        with _metrics_lock:
            return {
                "tool_runs": dict(_tool_runs),
                "tool_durations": dict(_tool_durations),
                "queue_depths": list(_queue_depths),
                "docker_failures": dict(_docker_failures),
                "agent_latencies": list(_agent_latencies),
            }
