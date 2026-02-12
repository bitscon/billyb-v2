import json
from pathlib import Path
from datetime import datetime
from v2.core.contracts.loader import ContractViolation

_V2_ROOT = Path(__file__).resolve().parents[2]


class ApprovalStore:
    """
    Append-only approval history with current state index.
    """

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else (_V2_ROOT / "var" / "approvals")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.base_dir / "history.jsonl"
        self.state_path = self.base_dir / "state.json"

    def request(self, plan_fingerprint: str, step_id: str, capability: str) -> dict:
        key = self._key(plan_fingerprint, step_id, capability)
        state = self._load_state()
        if key in state and state[key] in ("approved", "denied"):
            raise ContractViolation("Approval decision already recorded")

        record = {
            "plan_fingerprint": plan_fingerprint,
            "step_id": step_id,
            "capability": capability,
            "status": "pending",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._append_history(record)
        state[key] = "pending"
        self._save_state(state)
        return record

    def approve(self, plan_fingerprint: str, step_id: str, capability: str) -> dict:
        return self._decide(plan_fingerprint, step_id, capability, "approved")

    def deny(self, plan_fingerprint: str, step_id: str, capability: str) -> dict:
        return self._decide(plan_fingerprint, step_id, capability, "denied")

    def get_state(self, plan_fingerprint: str, step_id: str, capability: str) -> str | None:
        state = self._load_state()
        return state.get(self._key(plan_fingerprint, step_id, capability))

    def _decide(self, plan_fingerprint: str, step_id: str, capability: str, decision: str) -> dict:
        key = self._key(plan_fingerprint, step_id, capability)
        state = self._load_state()
        if state.get(key) != "pending":
            raise ContractViolation("Approval not pending")

        record = {
            "plan_fingerprint": plan_fingerprint,
            "step_id": step_id,
            "capability": capability,
            "status": decision,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._append_history(record)
        state[key] = decision
        self._save_state(state)
        return record

    def _append_history(self, record: dict) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a") as f:
            f.write(json.dumps(record))
            f.write("\n")

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        with self.state_path.open("r") as f:
            return json.load(f)

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")

    def _key(self, plan_fingerprint: str, step_id: str, capability: str) -> str:
        return f"{plan_fingerprint}:{step_id}:{capability}"
