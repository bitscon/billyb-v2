class PlanScorer:
    """
    Deterministic, advisory-only plan scoring.
    Lower score = safer / simpler.
    """

    def score(self, plan: dict) -> dict:
        score = 0
        reasons = []

        steps = plan.get("steps", [])
        risks = plan.get("risks", [])

        score += len(steps)
        if steps:
            reasons.append(f"{len(steps)} step(s)")

        score += len(risks) * 2
        if risks:
            reasons.append(f"{len(risks)} risk(s) identified")

        for step in steps:
            perms = step.get("requires_permissions", {})
            if perms.get("network", {}).get("outbound"):
                score += 3
                reasons.append("Outbound network access required")

        return {
            "score": score,
            "reasons": reasons,
        }
