"""Phase 7 memory primitives for post-execution recording and recall.

Memory is append-only and explicitly queryable. It does not influence decisions.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Protocol


@dataclass(frozen=True)
class MemoryEvent:
    timestamp: str
    intent: str
    tool_name: str
    parameters: Dict[str, Any]
    execution_result: Dict[str, Any]
    success: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MemoryStore(Protocol):
    def append(self, event: MemoryEvent) -> None:
        ...

    def get_last(self, count: int) -> List[MemoryEvent]:
        ...

    def get_by_intent(self, intent: str) -> List[MemoryEvent]:
        ...

    def get_by_tool(self, tool_name: str) -> List[MemoryEvent]:
        ...

    def clear(self) -> None:
        ...


class InMemoryMemoryStore:
    """Append-only in-memory memory store with deterministic ordering."""

    def __init__(self) -> None:
        self._events: List[MemoryEvent] = []

    def append(self, event: MemoryEvent) -> None:
        self._events.append(copy.deepcopy(event))

    def get_last(self, count: int) -> List[MemoryEvent]:
        if count <= 0:
            return []
        return copy.deepcopy(self._events[-count:])

    def get_by_intent(self, intent: str) -> List[MemoryEvent]:
        return [copy.deepcopy(e) for e in self._events if e.intent == intent]

    def get_by_tool(self, tool_name: str) -> List[MemoryEvent]:
        return [copy.deepcopy(e) for e in self._events if e.tool_name == tool_name]

    def clear(self) -> None:
        self._events = []


class FileBackedMemoryStore:
    """Append-only JSONL memory store for deterministic persistent replay."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def append(self, event: MemoryEvent) -> None:
        payload = json.dumps(event.to_dict(), ensure_ascii=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(payload + "\n")

    def get_last(self, count: int) -> List[MemoryEvent]:
        if count <= 0:
            return []
        events = self._read_all()
        return events[-count:]

    def get_by_intent(self, intent: str) -> List[MemoryEvent]:
        return [e for e in self._read_all() if e.intent == intent]

    def get_by_tool(self, tool_name: str) -> List[MemoryEvent]:
        return [e for e in self._read_all() if e.tool_name == tool_name]

    def clear(self) -> None:
        self._path.write_text("", encoding="utf-8")

    def _read_all(self) -> List[MemoryEvent]:
        events: List[MemoryEvent] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                events.append(
                    MemoryEvent(
                        timestamp=str(payload.get("timestamp", "")),
                        intent=str(payload.get("intent", "")),
                        tool_name=str(payload.get("tool_name", "")),
                        parameters=dict(payload.get("parameters", {})),
                        execution_result=dict(payload.get("execution_result", {})),
                        success=bool(payload.get("success", False)),
                    )
                )
        return events
