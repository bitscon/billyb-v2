import json
from pathlib import Path

_V2_ROOT = Path(__file__).resolve().parents[2]


class Forensics:
    """
    Read-only access to execution journal records.
    """

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else (_V2_ROOT / "var" / "executions")
        self.records_path = self.base_dir / "journal.jsonl"

    def _load(self) -> list[dict]:
        if not self.records_path.exists():
            return []
        with self.records_path.open("r") as f:
            return [json.loads(line) for line in f if line.strip()]

    def by_trace_id(self, trace_id: str) -> list[dict]:
        return [r for r in self._load() if r.get("execution", {}).get("trace_id") == trace_id]

    def by_plan_fingerprint(self, plan_fingerprint: str) -> list[dict]:
        return [
            r for r in self._load()
            if r.get("execution", {}).get("plan_fingerprint") == plan_fingerprint
        ]
