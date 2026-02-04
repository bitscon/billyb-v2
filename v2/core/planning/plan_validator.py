class PlanValidator:
    """
    Validates LLM-proposed plans.
    Untrusted input. Fail closed.
    """

    def validate(self, plan: dict, tool_specs: dict) -> dict:
        errors = []

        if not isinstance(plan, dict):
            return {"valid": False, "errors": ["Plan is not an object"]}

        steps = plan.get("steps", [])
        if not isinstance(steps, list):
            errors.append("steps must be a list")

        for step in steps:
            tool_id = step.get("tool_id")
            if tool_id and tool_id not in tool_specs:
                errors.append(f"Unknown tool_id: {tool_id}")

            if "args" in step and not isinstance(step["args"], (list, dict)):
                errors.append(f"Invalid args for step {step.get('step_id')}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }
