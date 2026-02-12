from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import json
import uuid

from v2.core.contracts.loader import ContractViolation

_V2_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    description: str
    required_evidence: List[str]
    required_capability: str
    ops_required: bool
    failure_modes: List[str]

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "required_evidence": list(self.required_evidence),
            "required_capability": self.required_capability,
            "ops_required": self.ops_required,
            "failure_modes": list(self.failure_modes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanStep":
        return cls(
            step_id=str(data["step_id"]),
            description=str(data["description"]),
            required_evidence=list(data.get("required_evidence") or []),
            required_capability=str(data.get("required_capability") or ""),
            ops_required=bool(data.get("ops_required")),
            failure_modes=list(data.get("failure_modes") or []),
        )


@dataclass(frozen=True)
class Plan:
    plan_id: str
    task_id: str
    steps: List[PlanStep]
    created_at: datetime
    approved: bool

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "steps": [step.to_dict() for step in self.steps],
            "created_at": _dt_to_iso(self.created_at),
            "approved": self.approved,
        }


PLANS_DIR = _V2_ROOT / "state" / "plans"
PLANS_DIR.mkdir(parents=True, exist_ok=True)


def create_plan(task_id: str, steps: List[PlanStep]) -> Plan:
    if not task_id:
        raise ContractViolation("Missing task_id.")
    if not steps:
        raise ContractViolation("Plan must include at least one step.")
    plan_id = str(uuid.uuid4())
    plan = Plan(
        plan_id=plan_id,
        task_id=task_id,
        steps=steps,
        created_at=_now(),
        approved=False,
    )
    _append_line(_plan_path(plan_id), {"type": "plan", "plan": plan.to_dict()})
    return plan


def approve_plan(plan_id: str) -> None:
    path = _plan_path(plan_id)
    if not path.exists():
        raise ContractViolation("Plan not found.")
    plan = get_plan(plan_id)
    if plan.approved:
        raise ContractViolation("Plan already approved.")
    _append_line(path, {"type": "approval", "plan_id": plan_id, "timestamp": _dt_to_iso(_now())})


def get_plan(plan_id: str) -> Plan:
    path = _plan_path(plan_id)
    if not path.exists():
        raise ContractViolation("Plan not found.")
    plan_data = None
    approved = False
    for record in _iter_records(path):
        if record.get("type") == "plan":
            plan_data = record.get("plan")
        elif record.get("type") == "approval":
            approved = True
    if not plan_data:
        raise ContractViolation("Plan data missing.")
    plan = Plan(
        plan_id=str(plan_data["plan_id"]),
        task_id=str(plan_data["task_id"]),
        steps=[PlanStep.from_dict(step) for step in plan_data.get("steps", [])],
        created_at=_dt_from_iso(plan_data["created_at"]),
        approved=approved,
    )
    return plan


def list_plans() -> List[str]:
    if not PLANS_DIR.exists():
        return []
    return sorted(path.stem for path in PLANS_DIR.glob("*.json"))


def find_plans_for_task(task_id: str) -> List[Plan]:
    plans = []
    for plan_id in list_plans():
        try:
            plan = get_plan(plan_id)
        except ContractViolation:
            continue
        if plan.task_id == task_id:
            plans.append(plan)
    return plans


def _plan_path(plan_id: str) -> Path:
    return PLANS_DIR / f"{plan_id}.json"


def _append_line(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _iter_records(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ContractViolation(f"Invalid plan record at line {line_num}.") from exc
            if not isinstance(data, dict):
                raise ContractViolation(f"Invalid plan record at line {line_num}.")
            yield data


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _dt_from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
