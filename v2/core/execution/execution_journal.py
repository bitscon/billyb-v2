import json
from pathlib import Path
from datetime import datetime


class ExecutionJournal:
    """
    Append-only execution journal.
    """

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or "v2/var/executions")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.base_dir / "journal.jsonl"

    def append(self, record: dict) -> None:
        with self.records_path.open("a") as f:
            f.write(json.dumps(record))
            f.write("\n")

    def build_record(
        self,
        trace_id: str,
        plan_fingerprint: str,
        step_id: str,
        capability: str,
        tool_name: str,
        tool_version: str,
        inputs: dict,
        status: str,
        reason: str,
        outputs: dict | None,
    ) -> dict:
        return {
            "execution": {
                "trace_id": trace_id,
                "plan_fingerprint": plan_fingerprint,
                "step_id": step_id,
                "capability": capability,
                "tool": {
                    "name": tool_name,
                    "version": tool_version,
                },
                "inputs": inputs,
                "outcome": {
                    "status": status,
                    "reason": reason,
                    "outputs": outputs,
                },
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        }
