import hashlib
import json


def _normalize_plan(plan: dict) -> dict:
    def _sorted_list(val):
        if isinstance(val, list):
            return sorted((_sorted_list(v) for v in val), key=lambda x: json.dumps(x, sort_keys=True))
        if isinstance(val, dict):
            return {k: _sorted_list(v) for k, v in sorted(val.items())}
        return val

    normalized = {
        "objective": plan.get("objective"),
        "assumptions": _sorted_list(plan.get("assumptions", [])),
        "steps": _sorted_list([
            {
                "step_id": s.get("step_id"),
                "description": s.get("description"),
                "inputs": s.get("inputs"),
                "outputs": s.get("outputs"),
                "validation": s.get("validation"),
            }
            for s in plan.get("steps", [])
        ]),
        "artifacts": _sorted_list([
            {
                "path": a.get("path"),
                "type": a.get("type"),
            }
            for a in plan.get("artifacts", [])
        ]),
        "risks": _sorted_list(plan.get("risks", [])),
    }
    return normalized


def fingerprint(plan: dict) -> str:
    normalized = _normalize_plan(plan)
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
