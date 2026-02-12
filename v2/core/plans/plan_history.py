import json
from pathlib import Path
from datetime import datetime

_V2_ROOT = Path(__file__).resolve().parents[2]


class PlanHistory:
    """
    Append-only plan history with separate mutable status index.
    """

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else (_V2_ROOT / "var" / "plans")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.base_dir / "records.jsonl"
        self.status_path = self.base_dir / "status.json"

    def append(self, plan: dict, fingerprint: str) -> dict:
        record = {
            "fingerprint": fingerprint,
            "plan": plan,
            "version": plan.get("version"),
            "promoted_at": datetime.utcnow().isoformat() + "Z",
        }
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        with self.records_path.open("a") as f:
            f.write(json.dumps(record))
            f.write("\n")
        return record

    def list_records(self) -> list[dict]:
        if not self.records_path.exists():
            return []
        with self.records_path.open("r") as f:
            return [json.loads(line) for line in f if line.strip()]

    def get(self, fingerprint: str) -> dict | None:
        for rec in self.list_records():
            if rec.get("fingerprint") == fingerprint:
                return rec
        return None

    def exists(self, fingerprint: str) -> bool:
        return self.get(fingerprint) is not None

    def get_active(self) -> str | None:
        status = self._load_status()
        return status.get("active_fingerprint")

    def set_active(self, fingerprint: str) -> None:
        status = self._load_status()
        previous = status.get("active_fingerprint")
        if previous:
            status.setdefault("states", {})[previous] = "inactive"
        status.setdefault("states", {})[fingerprint] = "active"
        status["active_fingerprint"] = fingerprint
        self._save_status(status)

    def mark_rolled_back(self, fingerprint: str) -> None:
        status = self._load_status()
        status.setdefault("states", {})[fingerprint] = "rolled_back"
        self._save_status(status)

    def record_rollback(self, from_fp: str | None, to_fp: str) -> None:
        status = self._load_status()
        status.setdefault("rollbacks", []).append({
            "from_fingerprint": from_fp,
            "to_fingerprint": to_fp,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        self._save_status(status)

    def _load_status(self) -> dict:
        if not self.status_path.exists():
            return {"states": {}, "active_fingerprint": None, "rollbacks": []}
        with self.status_path.open("r") as f:
            return json.load(f)

    def _save_status(self, status: dict) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        with self.status_path.open("w") as f:
            json.dump(status, f, indent=2)
            f.write("\n")
