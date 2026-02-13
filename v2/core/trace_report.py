"""Trace report data models for command-interpreter observability replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List


@dataclass(frozen=True)
class TelemetryEvent:
    session_id: str
    correlation_id: str
    timestamp: str
    phase: str
    event_type: str
    metadata: Dict[str, Any]

    @property
    def timestamp_dt(self) -> datetime:
        return datetime.fromisoformat(self.timestamp)


@dataclass(frozen=True)
class TraceReport:
    session_id: str
    events: List[TelemetryEvent]
    event_count: int


def build_trace_report(session_id: str, events: List[TelemetryEvent]) -> TraceReport:
    ordered = sorted(events, key=lambda event: event.timestamp)
    return TraceReport(
        session_id=session_id,
        events=ordered,
        event_count=len(ordered),
    )
