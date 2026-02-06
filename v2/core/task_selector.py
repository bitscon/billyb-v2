from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict
import shlex

from core.task_graph import TaskNode
from core.evidence import load_evidence, has_evidence


@dataclass(frozen=True)
class SelectionContext:
    user_input: str
    trace_id: str
    via_ops: bool


@dataclass(frozen=True)
class SelectionResult:
    status: str
    task_id: Optional[str]
    reason: Optional[str]


def select_next_task(tasks: List[TaskNode], context: SelectionContext) -> SelectionResult:
    if not tasks:
        return SelectionResult(status="blocked", task_id=None, reason="No eligible tasks.\nBlocked because:\n- no tasks")

    load_evidence(context.trace_id)

    task_map: Dict[str, TaskNode] = {task.task_id: task for task in tasks}

    def deps_done(task: TaskNode) -> bool:
        for dep_id in task.depends_on:
            dep = task_map.get(dep_id)
            if not dep or dep.status != "done":
                return False
        return True

    def depth(task_id: str, seen: Optional[set[str]] = None) -> int:
        if seen is None:
            seen = set()
        if task_id in seen:
            return 0
        seen.add(task_id)
        node = task_map.get(task_id)
        if not node or not node.depends_on:
            return 0
        return 1 + max((depth(dep_id, seen) for dep_id in node.depends_on), default=0)

    def extract_evidence(description: str) -> List[str]:
        normalized = description.strip()
        evidence = []
        if normalized.lower().startswith("claim:"):
            claim = normalized.split(":", 1)[1].strip()
            if claim:
                evidence.append(claim)
        if "evidence:" in normalized.lower():
            _, tail = normalized.split("evidence:", 1)
            for item in tail.split(","):
                claim = item.strip()
                if claim:
                    evidence.append(claim)
        return evidence

    def extract_capability(description: str) -> tuple[str, str, bool]:
        normalized = description.strip()
        if normalized.startswith("/ops "):
            rest = normalized[len("/ops "):].strip()
            parts = shlex.split(rest)
            if len(parts) == 2:
                verb, target = parts
                capability = {
                    "restart": "restart_service",
                    "start": "start_service",
                    "stop": "stop_service",
                    "enable": "enable_service",
                    "disable": "disable_service",
                }.get(verb, "")
                return capability, f"{verb} {target}", True
        if normalized.startswith("/exec "):
            command = normalized[len("/exec "):].strip()
            parts = shlex.split(command)
            if parts:
                if parts[0] in ("touch", "mkdir"):
                    return "filesystem.write", command, False
                if parts[0] == "rm":
                    return "filesystem.delete", command, False
                if parts[0] in ("cat", "ls"):
                    return "filesystem.read", command, False
                if parts[0] == "git" and len(parts) == 2 and parts[1] == "push":
                    return "git.push", command, False
        return "", "", False

    ineligible_reasons: Dict[str, List[str]] = {}

    def eligible(task: TaskNode) -> bool:
        reasons = []
        if task.status != "ready":
            reasons.append(f"not ready: {task.status}")
        if not deps_done(task):
            reasons.append("dependencies not done")

        capability, action_text, via_ops_task = extract_capability(task.description)
        contract = None
        if capability:
            status, contract = _contract_status(capability)
            if status == "missing":
                reasons.append(f"missing capability contract: {capability}")
            elif status == "ambiguous":
                reasons.append(f"capability contract is ambiguous: {capability}")
            elif status == "invalid":
                reasons.append(f"capability contract is invalid: {capability}")
        if contract:
            if contract.get("requires", {}).get("ops_required") and not context.via_ops:
                reasons.append(f"requires /ops: {action_text}")
            required_evidence = extract_evidence(task.description) + contract.get("requires", {}).get("evidence", [])
        else:
            required_evidence = extract_evidence(task.description)

        for claim in required_evidence:
            if not has_evidence(claim):
                reasons.append(f"missing evidence: {claim}")

        if reasons:
            ineligible_reasons[task.task_id] = reasons
            return False
        return True

    eligible_tasks = [task for task in tasks if eligible(task)]

    def is_explicit(task: TaskNode) -> bool:
        text = context.user_input.lower()
        if task.task_id in text:
            return True
        return task.description.lower() in text

    explicit_candidates = [task for task in eligible_tasks if is_explicit(task)]

    candidates = explicit_candidates or eligible_tasks
    if not candidates:
        reason_lines = ["No eligible tasks.", "Blocked because:"]
        for task_id in sorted(ineligible_reasons.keys()):
            reasons = ineligible_reasons[task_id]
            for reason in reasons:
                reason_lines.append(f"- task {task_id} {reason}")
        if len(reason_lines) == 2:
            reason_lines.append("- no eligible tasks")
        return SelectionResult(status="blocked", task_id=None, reason="\n".join(reason_lines))

    candidates.sort(
        key=lambda task: (
            task.created_at,
            depth(task.task_id),
            task.task_id,
        )
    )
    selected = candidates[0]
    return SelectionResult(status="selected", task_id=selected.task_id, reason="selected by deterministic rules")


def _contract_status(capability: str):
    from core import capability_contracts

    matches = []
    invalid = False
    for path in capability_contracts.CAPABILITY_DIR.glob("*.yaml"):
        try:
            data = path.read_text(encoding="utf-8")
        except Exception:
            invalid = True
            continue
        try:
            import yaml

            parsed = yaml.safe_load(data)
        except Exception:
            invalid = True
            continue
        if not isinstance(parsed, dict):
            invalid = True
            continue
        if parsed.get("capability") == capability:
            matches.append(parsed)

    if len(matches) == 0:
        return "missing", None
    if len(matches) > 1:
        return "ambiguous", None
    contract = matches[0]
    if not _valid_contract_schema(contract):
        return "invalid", None
    return "ok", contract


def _valid_contract_schema(contract: dict) -> bool:
    if contract.get("risk_level") not in ("low", "medium", "high"):
        return False
    requires = contract.get("requires")
    if not isinstance(requires, dict):
        return False
    if "ops_required" not in requires or "evidence" not in requires:
        return False
    if not isinstance(requires.get("evidence"), list):
        return False
    guarantees = contract.get("guarantees")
    if guarantees is None or not isinstance(guarantees, list):
        return False
    return True
