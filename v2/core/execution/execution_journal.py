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

    def build_resolution_record(
        self,
        trace_id: str,
        task_id: str,
        resolution_type: str,
        resolution_message: str,
        next_step: str | None,
        evidence_fingerprint: str,
        contract_version: str,
        terminal: bool = True,
        linked_task_id: str | None = None,
    ) -> dict:
        record = {
            "resolution": {
                "trace_id": trace_id,
                "task_id": task_id,
                "resolution_type": resolution_type,
                "resolution_message": resolution_message,
                "next_step": next_step,
                "evidence_fingerprint": evidence_fingerprint,
                "contract_version": contract_version,
                "terminal": terminal,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        }
        if linked_task_id is not None:
            record["resolution"]["linked_task_id"] = linked_task_id
        return record

    def build_inspection_origination_record(
        self,
        trace_id: str,
        origin_task_id: str,
        new_task_id: str,
        description: str,
    ) -> dict:
        return {
            "inspection_task": {
                "trace_id": trace_id,
                "origin_task_id": origin_task_id,
                "new_task_id": new_task_id,
                "description": description,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        }

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
