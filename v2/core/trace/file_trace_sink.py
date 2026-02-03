import json
from pathlib import Path
from datetime import datetime

class FileTraceSink:
    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or "v2/var/traces")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def emit(self, event: dict) -> None:
        trace_id = event["trace_id"]
        trace_file = self.base_dir / f"{trace_id}.jsonl"

        with trace_file.open("a") as f:
            f.write(json.dumps(event))
            f.write("\n")

    def flush(self, trace_id: str) -> None:
        # no-op for file-based sink
        return

    def get_trace(self, trace_id: str) -> list[dict]:
        trace_file = self.base_dir / f"{trace_id}.jsonl"
        if not trace_file.exists():
            return []

        with trace_file.open("r") as f:
            return [json.loads(line) for line in f]
