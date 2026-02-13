"""Passive observability store for command-interpreter telemetry."""

from __future__ import annotations

import copy
import hashlib
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List

from v2.core.trace_report import TelemetryEvent


_SENSITIVE_KEYWORDS = ("utterance", "prompt", "content", "text", "message", "raw", "user_input", "response")

_SESSION_ID_CTX: ContextVar[str | None] = ContextVar("cmd_obs_session_id", default=None)
_CORRELATION_ID_CTX: ContextVar[str | None] = ContextVar("cmd_obs_correlation_id", default=None)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_session_id() -> str:
    return f"sess-{uuid.uuid4()}"


def _new_correlation_id() -> str:
    return f"corr-{uuid.uuid4()}"


def mask_text(value: Any) -> str:
    text = str(value)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"<masked:len={len(text)}:sha256_12={digest}>"


def _sanitize_value(key: str, value: Any) -> Any:
    lowered_key = key.lower()
    if any(token in lowered_key for token in _SENSITIVE_KEYWORDS):
        return mask_text(value)
    if isinstance(value, dict):
        return {str(k): _sanitize_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(f"{key}_item", item) for item in value]
    return value


def sanitize_metadata(metadata: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {str(key): _sanitize_value(str(key), value) for key, value in metadata.items()}


class _TelemetryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: List[TelemetryEvent] = []

    def append(self, event: TelemetryEvent) -> None:
        with self._lock:
            self._events.append(event)

    def by_session(self, session_id: str) -> List[TelemetryEvent]:
        with self._lock:
            return [copy.deepcopy(event) for event in self._events if event.session_id == session_id]

    def reset(self) -> None:
        with self._lock:
            self._events = []


_STORE = _TelemetryStore()


def current_session_id() -> str | None:
    return _SESSION_ID_CTX.get()


def current_correlation_id() -> str | None:
    return _CORRELATION_ID_CTX.get()


@contextmanager
def observability_turn(session_id: str | None = None, correlation_id: str | None = None) -> Iterator[tuple[str, str]]:
    resolved_session = (session_id or current_session_id() or _new_session_id()).strip()
    resolved_correlation = (correlation_id or _new_correlation_id()).strip()
    token_session = _SESSION_ID_CTX.set(resolved_session)
    token_correlation = _CORRELATION_ID_CTX.set(resolved_correlation)
    try:
        yield resolved_session, resolved_correlation
    finally:
        _SESSION_ID_CTX.reset(token_session)
        _CORRELATION_ID_CTX.reset(token_correlation)


@contextmanager
def ensure_observability_context(session_id: str | None = None) -> Iterator[tuple[str, str]]:
    if current_session_id() and current_correlation_id():
        yield current_session_id() or "", current_correlation_id() or ""
        return
    with observability_turn(session_id=session_id) as ctx:
        yield ctx


def log_telemetry_event(phase: str, event_type: str, metadata: Dict[str, Any] | None = None) -> None:
    try:
        session_id = current_session_id() or _new_session_id()
        correlation_id = current_correlation_id() or _new_correlation_id()
        event = TelemetryEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=_utcnow_iso(),
            phase=str(phase),
            event_type=str(event_type),
            metadata=sanitize_metadata(metadata),
        )
        _STORE.append(event)
    except Exception:
        # Observability must not influence runtime behavior.
        return


def get_session_events(session_id: str) -> List[TelemetryEvent]:
    return _STORE.by_session(session_id=session_id)


def reset_telemetry_events() -> None:
    _STORE.reset()
