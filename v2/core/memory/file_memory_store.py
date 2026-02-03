import json
import uuid
from pathlib import Path
from datetime import datetime
from core.contracts.loader import ContractViolation, validate_trace_event


class FileMemoryStore:
    def __init__(self, base_dir: str | None = None, trace_sink=None):
        self.base_dir = Path(base_dir or "v2/var/memory")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.trace_sink = trace_sink

    def write(self, entry: dict, trace_id: str) -> dict:
        if "content" not in entry or "metadata" not in entry or "scope" not in entry:
            raise ContractViolation("Invalid MemoryEntry")

        entry_id = entry.get("id") or str(uuid.uuid4())
        entry["id"] = entry_id

        path = self.base_dir / f"{entry_id}.json"
        with path.open("w") as f:
            json.dump(entry, f, indent=2)

        self._emit(trace_id, "memory_write_success", {"memory_id": entry_id})
        return entry

    def query(self, scope: dict, trace_id: str) -> list[dict]:
        results = []
        for path in self.base_dir.glob("*.json"):
            with path.open("r") as f:
                entry = json.load(f)

            if self._scope_match(entry.get("scope", {}), scope):
                results.append(entry)

        self._emit(trace_id, "memory_query", {"count": len(results)})
        return results

    def _scope_match(self, entry_scope: dict, query_scope: dict) -> bool:
        for key, val in query_scope.items():
            if val is not None and entry_scope.get(key) != val:
                return False
        return True

    def _emit(self, trace_id: str, event_type: str, payload: dict):
        if not self.trace_sink:
            return

        event = {
            "trace_id": trace_id,
            "event_id": f"{event_type}-{int(datetime.utcnow().timestamp()*1000)}",
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "actor": {"component": "memory_store"},
            "payload": payload,
        }
        validate_trace_event(event)
        self.trace_sink.emit(event)
