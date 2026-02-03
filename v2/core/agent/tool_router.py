from core.contracts.loader import ContractViolation

class ToolRouter:
    """
    Deterministic mapping from user input -> tool_id.
    No AI. No guessing.
    """

    def __init__(self, registry):
        self.registry = registry

    def route(self, user_input: str) -> str | None:
        normalized = user_input.strip().lower()

        if normalized == "run hello":
            return "demo.hello"

        return None
