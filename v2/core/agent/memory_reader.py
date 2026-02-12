class MemoryReader:
    """
    Explicit mapping from user input -> memory read intent.
    No inference. No guessing.
    """

    def route_read(self, user_input: str) -> dict | None:
        normalized = user_input.strip().lower()

        if normalized == "recall" or normalized.startswith("recall "):
            return {
                "user_id": "default",
                "persona_id": None,
                "session_id": None,
            }

        return None
