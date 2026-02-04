from core.contracts.loader import ContractViolation

class ToolGuard:
    """
    Validates tool calls against registered contracts.
    """

    TYPE_MAP = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "object": dict,
        "array": list,
    }

    def validate(self, contract: dict, inputs: dict) -> dict:
        errors = []

        tool = contract.get("tool", {})
        schema = tool.get("inputs", [])

        if not isinstance(inputs, dict):
            return {"valid": False, "errors": ["Inputs must be an object"]}

        allowed_names = {i.get("name") for i in schema if isinstance(i, dict)}
        for name, spec in ((i.get("name"), i) for i in schema if isinstance(i, dict)):
            if spec.get("required") and name not in inputs:
                errors.append(f"Missing required input: {name}")
            if name in inputs:
                expected = self.TYPE_MAP.get(spec.get("type"))
                if expected and not isinstance(inputs[name], expected):
                    errors.append(f"Invalid type for input {name}")

        for name in inputs.keys():
            if name not in allowed_names:
                errors.append(f"Unexpected input: {name}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }
