from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional


ResolutionType = Literal["RESOLVED", "BLOCKED", "ESCALATE", "FOLLOW_UP_INSPECTION"]


@dataclass(frozen=True)
class ResolutionOutcome:
    outcome_type: ResolutionType
    message: str
    next_step: Optional[str] = None
    rule_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "outcome_type": self.outcome_type,
            "message": self.message,
        }
        if self.next_step is not None:
            payload["next_step"] = self.next_step
        if self.rule_id is not None:
            payload["rule_id"] = self.rule_id
        if self.details is not None:
            payload["details"] = self.details
        return payload
