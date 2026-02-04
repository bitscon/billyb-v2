class PlanValidator:
    """
    Validates LLM-proposed plans.
    Untrusted input. Fail closed.
    """

    REQUIRED_FIELDS = [
        "id",
        "version",
        "objective",
        "assumptions",
        "steps",
        "artifacts",
        "risks",
        "outputs",
        "validation",
    ]

    def validate(self, plan: dict) -> dict:
        errors = []

        if not isinstance(plan, dict):
            return {"valid": False, "errors": ["Plan is not an object"]}

        for field in self.REQUIRED_FIELDS:
            if field not in plan:
                errors.append(f"Missing required field: {field}")

        steps = plan.get("steps")
        if not isinstance(steps, list) or len(steps) == 0:
            errors.append("steps must be a non-empty list")
        else:
            for step in steps:
                if not isinstance(step, dict):
                    errors.append("step must be an object")
                    continue
                if not step.get("step_id") or not step.get("description"):
                    errors.append("step_id and description are required")

        outputs = plan.get("outputs")
        if not isinstance(outputs, list) or len(outputs) == 0:
            errors.append("outputs must be a non-empty list")

        validation = plan.get("validation")
        if not isinstance(validation, list) or len(validation) == 0:
            errors.append("validation must be a non-empty list")

        artifacts = plan.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append("artifacts must be a list")
        else:
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    errors.append("artifact must be an object")
                    continue
                if not artifact.get("checksum"):
                    errors.append("artifact missing checksum")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }
