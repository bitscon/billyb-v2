"""Phase 16 content-capture primitives.

Captured content is explicit, append-only, and auditable. It does not alter
policy/approval authority by itself.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Protocol


@dataclass(frozen=True)
class CapturedContent:
    content_id: str
    type: str
    source: str
    text: str
    timestamp: str
    origin_turn_id: str
    label: str
    session_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ContentCaptureStore(Protocol):
    def append(self, content: CapturedContent) -> None:
        ...

    def get_last(self, count: int) -> List[CapturedContent]:
        ...

    def get_by_id(self, content_id: str) -> CapturedContent | None:
        ...

    def get_by_label(self, label: str) -> List[CapturedContent]:
        ...

    def clear(self) -> None:
        ...


class InMemoryContentCaptureStore:
    """Append-only in-memory content capture store."""

    def __init__(self) -> None:
        self._items: List[CapturedContent] = []

    def append(self, content: CapturedContent) -> None:
        self._items.append(copy.deepcopy(content))

    def get_last(self, count: int) -> List[CapturedContent]:
        if count <= 0:
            return []
        return copy.deepcopy(self._items[-count:])

    def get_by_id(self, content_id: str) -> CapturedContent | None:
        key = str(content_id).strip()
        if not key:
            return None
        for item in self._items:
            if item.content_id == key:
                return copy.deepcopy(item)
        return None

    def get_by_label(self, label: str) -> List[CapturedContent]:
        key = str(label).strip().lower()
        if not key:
            return []
        return [copy.deepcopy(item) for item in self._items if item.label.strip().lower() == key]

    def clear(self) -> None:
        self._items = []


class FileBackedContentCaptureStore:
    """Append-only JSONL store for captured content."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def append(self, content: CapturedContent) -> None:
        payload = json.dumps(content.to_dict(), ensure_ascii=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(payload + "\n")

    def get_last(self, count: int) -> List[CapturedContent]:
        if count <= 0:
            return []
        items = self._read_all()
        return items[-count:]

    def get_by_id(self, content_id: str) -> CapturedContent | None:
        key = str(content_id).strip()
        if not key:
            return None
        for item in self._read_all():
            if item.content_id == key:
                return item
        return None

    def get_by_label(self, label: str) -> List[CapturedContent]:
        key = str(label).strip().lower()
        if not key:
            return []
        return [item for item in self._read_all() if item.label.strip().lower() == key]

    def clear(self) -> None:
        self._path.write_text("", encoding="utf-8")

    def _read_all(self) -> List[CapturedContent]:
        items: List[CapturedContent] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                row = line.strip()
                if not row:
                    continue
                payload = json.loads(row)
                items.append(
                    CapturedContent(
                        content_id=str(payload.get("content_id", "")),
                        type=str(payload.get("type", "text")),
                        source=str(payload.get("source", "")),
                        text=str(payload.get("text", "")),
                        timestamp=str(payload.get("timestamp", "")),
                        origin_turn_id=str(payload.get("origin_turn_id", "")),
                        label=str(payload.get("label", "")),
                        session_id=str(payload.get("session_id", "")),
                    )
                )
        return items
