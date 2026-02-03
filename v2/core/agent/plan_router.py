class PlanRouter:
    """
    Explicit routing for /plan mode.
    Read-only reasoning only.
    """

    def route(self, user_input: str) -> str | None:
        normalized = user_input.strip().lower()

        if normalized.startswith("/plan"):
            return normalized[len("/plan"):].strip()

        return None
