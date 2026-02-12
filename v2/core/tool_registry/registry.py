from v2.core.contracts.loader import validate_tool_spec, ContractViolation

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, tool_spec: dict) -> None:
        validate_tool_spec(tool_spec)
        tool_id = tool_spec["id"]
        self._tools[tool_id] = tool_spec

    def get(self, tool_id: str) -> dict:
        if tool_id not in self._tools:
            raise ContractViolation(f"Tool not registered: {tool_id}")
        return self._tools[tool_id]
