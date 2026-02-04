class ApprovalFlow:
    """
    Builds deterministic approval request payloads.
    """

    def build_request(self, plan_fingerprint: str, step_id: str, capability: str, tool: dict, safety: dict) -> dict:
        return {
            "approval_request": {
                "plan_fingerprint": plan_fingerprint,
                "step_id": step_id,
                "capability": capability,
                "tool": {
                    "name": tool.get("name"),
                    "version": tool.get("version"),
                },
                "risk": {
                    "reversible": safety.get("reversible"),
                    "destructive": safety.get("destructive"),
                },
            }
        }
