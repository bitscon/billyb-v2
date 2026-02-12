import yaml
from pathlib import Path
from v2.core.contracts.loader import validate_tool_spec, ContractViolation

class ToolLoader:
    def __init__(self, tools_dir: str):
        self.tools_dir = Path(tools_dir)

    def load_all(self) -> list[dict]:
        if not self.tools_dir.exists():
            raise ContractViolation(f"Tools directory not found: {self.tools_dir}")

        specs: list[dict] = []

        for path in sorted(self.tools_dir.glob("*.yaml")):
            with path.open("r") as f:
                spec = yaml.safe_load(f)

            validate_tool_spec(spec)
            specs.append(spec)

        return specs
