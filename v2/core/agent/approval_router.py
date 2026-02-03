class ApprovalRouter:
    """
    Explicit approval for executing a previously generated plan.
    """

    def route(self, user_input: str) -> str | None:
        normalized = user_input.strip().lower()

        if normalized.startswith("/approve"):
            return normalized[len("/approve"):].strip()

        return None
