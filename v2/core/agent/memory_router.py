from v2.core.contracts.loader import ContractViolation

class MemoryRouter:
    """
    Explicit mapping from user input -> memory write intent.
    No inference. No guessing.
    """

    def route_write(self, user_input: str) -> dict | None:
        normalized = user_input.strip()

        if normalized.lower().startswith("remember:"):
            content = normalized[len("remember:"):].strip()
            if not content:
                raise ContractViolation("Empty memory content")

            return {
                "content": content,
                "scope": {
                    "user_id": "default",
                    "persona_id": None,
                    "session_id": None,
                },
                "metadata": {
                    "category": "user_note",
                    "confidence": 1.0,
                    "importance": "medium",
                    "source": "user",
                },
            }

        return None
