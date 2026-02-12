from v2.core.contracts.loader import ContractViolation
from v2.core.tools.tool_contract import ToolContract

class CapabilityRegistry:
    def __init__(self):
        self._contracts: dict[str, dict[str, dict]] = {}
        self._capabilities: dict[str, tuple[str, str]] = {}

    def register(self, contract: dict) -> None:
        validated = ToolContract(contract).to_dict()
        tool = validated.get("tool", {})
        name = tool.get("name")
        version = tool.get("version")
        if not name or not version:
            raise ContractViolation("Tool contract missing name or version")

        if name not in self._contracts:
            self._contracts[name] = {}

        if version in self._contracts[name]:
            raise ContractViolation(f"Duplicate contract registration: {name}@{version}")

        capability = validated.get("capability")
        if capability in self._capabilities:
            raise ContractViolation(f"Duplicate capability registration: {capability}")

        self._contracts[name][version] = validated
        self._capabilities[capability] = (name, version)

    def is_registered(self, tool_name: str, version: str) -> bool:
        return tool_name in self._contracts and version in self._contracts[tool_name]

    def get_contract(self, tool_name: str, version: str) -> dict:
        if not self.is_registered(tool_name, version):
            raise ContractViolation(f"Tool not registered: {tool_name}@{version}")
        return self._contracts[tool_name][version]

    def resolve(self, capability: str) -> tuple[str, str, dict]:
        if capability not in self._capabilities:
            raise ContractViolation(f"Capability not registered: {capability}")
        name, version = self._capabilities[capability]
        return name, version, self.get_contract(name, version)
