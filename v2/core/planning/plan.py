import uuid
from datetime import datetime

class Plan:
    def __init__(self, intent: str, steps: list[dict], assumptions=None, risks=None):
        self.plan = {
            "plan_id": str(uuid.uuid4()),
            "intent": intent,
            "assumptions": assumptions or [],
            "steps": steps,
            "risks": risks or [],
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

    def to_dict(self) -> dict:
        return self.plan
