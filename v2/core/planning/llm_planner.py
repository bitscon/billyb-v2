class LLMPlanner:
    """
    Proposes multiple candidate plans (advisory only).
    Deterministic stub; LLM hook later.
    """

    def propose_many(self, intent: str, tool_specs: dict) -> list[dict]:
        proposals = []

        # Plan A — minimal
        if "demo.hello" in tool_specs:
            spec = tool_specs["demo.hello"]
            proposals.append({
                "intent": intent,
                "assumptions": ["Minimal execution preferred"],
                "steps": [{
                    "step_id": "a-step-1",
                    "description": "Run hello world tool",
                    "tool_id": "demo.hello",
                    "args": [],
                    "requires_permissions": spec["permissions"],
                }],
                "risks": ["Single-step plan"],
            })

        # Plan B — conservative (no tools)
        proposals.append({
            "intent": intent,
            "assumptions": ["User may want review before execution"],
            "steps": [],
            "risks": ["No tools selected; may not achieve intent"],
        })

        return proposals
