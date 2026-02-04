import json


def _map_steps(steps):
    return {s.get("step_id"): s for s in steps or [] if isinstance(s, dict) and s.get("step_id")}


def _map_artifacts(artifacts):
    return {f"{a.get('path')}|{a.get('type')}": a for a in artifacts or [] if isinstance(a, dict)}


def diff_plans(old: dict, new: dict) -> dict:
    old_steps = _map_steps(old.get("steps", []))
    new_steps = _map_steps(new.get("steps", []))

    added_steps = [new_steps[k] for k in new_steps.keys() - old_steps.keys()]
    removed_steps = [old_steps[k] for k in old_steps.keys() - new_steps.keys()]

    modified_steps = []
    for step_id in new_steps.keys() & old_steps.keys():
        before = old_steps[step_id]
        after = new_steps[step_id]
        if json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
            modified_steps.append({
                "step_id": step_id,
                "before": before,
                "after": after,
                "impact": "high",
            })

    old_artifacts = _map_artifacts(old.get("artifacts", []))
    new_artifacts = _map_artifacts(new.get("artifacts", []))
    artifact_changes = []

    for k in new_artifacts.keys() - old_artifacts.keys():
        artifact_changes.append({"type": "added", "artifact": new_artifacts[k]})
    for k in old_artifacts.keys() - new_artifacts.keys():
        artifact_changes.append({"type": "removed", "artifact": old_artifacts[k]})

    old_risks = set(old.get("risks", []) or [])
    new_risks = set(new.get("risks", []) or [])
    risk_changes = []

    for r in new_risks - old_risks:
        risk_changes.append({"type": "added", "risk": r})
    for r in old_risks - new_risks:
        risk_changes.append({"type": "removed", "risk": r})

    summary = "no changes"
    if added_steps or removed_steps or modified_steps or artifact_changes or risk_changes:
        summary = "changes detected"

    return {
        "diff": {
            "added_steps": added_steps,
            "removed_steps": removed_steps,
            "modified_steps": modified_steps,
            "artifact_changes": artifact_changes,
            "risk_changes": risk_changes,
            "summary": summary,
        }
    }
