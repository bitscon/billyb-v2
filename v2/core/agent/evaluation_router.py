class EvaluationRouter:
    """
    Explicit routing for evaluation requests.
    No memory writes. No execution.
    """

    def route(self, user_input: str) -> dict | None:
        normalized = user_input.strip().lower()

        if normalized.startswith("/evaluate"):
            parts = normalized.split(maxsplit=2)
            if len(parts) < 3:
                return None

            subject_type = parts[1]
            subject_id = parts[2]

            return {
                "subject_type": subject_type,
                "subject_id": subject_id,
            }

        return None
