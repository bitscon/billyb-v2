from v2.core.contracts.loader import ContractViolation

class PromotionRouter:
    """
    Explicit promotion of evaluation summaries into memory.
    Manual only.
    """

    def route(self, user_input: str) -> bool:
        normalized = user_input.strip().lower()
        if normalized == "/promote":
            return True
        return False
