from core.contracts.loader import ContractViolation


class ToolContract:
    """
    Defines a tool contract schema.
    """

    REQUIRED_TOOL_FIELDS = [
        "name",
        "version",
        "inputs",
        "outputs",
        "safety",
    ]

    def __init__(self, contract: dict):
        if not isinstance(contract, dict):
            raise ContractViolation("Tool contract must be an object")

        if "capability" not in contract or not contract.get("capability"):
            raise ContractViolation("Tool contract missing capability")

        tool = contract.get("tool")
        if not isinstance(tool, dict):
            raise ContractViolation("Tool contract missing tool section")

        for field in self.REQUIRED_TOOL_FIELDS:
            if field not in tool:
                raise ContractViolation(f"Tool contract missing field: {field}")

        if not isinstance(tool.get("inputs"), list):
            raise ContractViolation("Tool inputs must be a list")
        if not isinstance(tool.get("outputs"), list):
            raise ContractViolation("Tool outputs must be a list")
        safety = tool.get("safety")
        if not isinstance(safety, dict):
            raise ContractViolation("Tool safety must be an object")
        for field in ("reversible", "destructive", "requires_approval"):
            if field not in safety:
                raise ContractViolation(f"Tool safety missing field: {field}")

        self.contract = contract

    def to_dict(self) -> dict:
        return self.contract
