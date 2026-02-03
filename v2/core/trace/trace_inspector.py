import json
from pathlib import Path

class TraceInspector:
    def __init__(self, trace_dir: str = "v2/var/traces"):
        self.trace_dir = Path(trace_dir)

    def list_traces(self) -> list[str]:
        if not self.trace_dir.exists():
            return []
        return [p.stem for p in self.trace_dir.glob("*.jsonl")]

    def load(self, trace_id: str) -> list[dict]:
        path = self.trace_dir / f"{trace_id}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"Trace not found: {trace_id}")

        with path.open("r") as f:
            return [json.loads(line) for line in f]

    def summarize(self, trace_id: str) -> dict:
        events = self.load(trace_id)
        summary = {
            "trace_id": trace_id,
            "events": len(events),
            "components": sorted({e["actor"]["component"] for e in events}),
            "event_types": sorted({e["event_type"] for e in events}),
        }
        return summary
