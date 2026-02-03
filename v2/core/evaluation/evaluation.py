from datetime import datetime

class Evaluation:
    """
    Read-only evaluation of a completed step or plan.
    """

    def __init__(
        self,
        subject_type: str,   # "step" or "plan"
        subject_id: str,
        outcome: str,        # success | failed | aborted
        observations: list[str],
        risks: list[str] | None = None,
    ):
        self.evaluation = {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "outcome": outcome,
            "observations": observations,
            "risks": risks or [],
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

    def to_dict(self) -> dict:
        return self.evaluation
