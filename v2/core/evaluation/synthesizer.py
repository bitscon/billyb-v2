class EvaluationSynthesizer:
    """
    Converts Evaluation objects into human-readable summaries.
    Read-only. Deterministic.
    """

    def summarize(self, evaluation: dict) -> str:
        lines = [
            f"Evaluation for {evaluation['subject_type']} {evaluation['subject_id']}:",
            f"Outcome: {evaluation['outcome']}",
        ]

        if evaluation.get("observations"):
            lines.append("Observations:")
            for o in evaluation["observations"]:
                lines.append(f"- {o}")

        if evaluation.get("risks"):
            lines.append("Risks:")
            for r in evaluation["risks"]:
                lines.append(f"- {r}")

        return "\n".join(lines)
