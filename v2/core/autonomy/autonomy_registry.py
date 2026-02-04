import time
from core.contracts.loader import ContractViolation


class AutonomyRegistry:
    """
    Runtime-owned autonomy policy registry with limits enforcement.
    """

    def __init__(self):
        self._policies: dict[str, dict] = {}
        self._history: dict[str, list[float]] = {}
        self._step_history: dict[str, set[str]] = {}

    def register(self, policy: dict) -> None:
        if not isinstance(policy, dict):
            raise ContractViolation("Autonomy policy must be an object")
        autonomy = policy.get("autonomy", {})
        capability = autonomy.get("capability")
        if not capability:
            raise ContractViolation("Autonomy policy missing capability")
        self._policies[capability] = policy

    def revoke_autonomy(self, capability: str) -> None:
        if capability not in self._policies:
            raise ContractViolation("Autonomy policy not found")
        self._policies[capability]["autonomy"]["enabled"] = False

    def is_autonomy_allowed(self, capability: str, context: dict) -> tuple[bool, str]:
        policy = self._policies.get(capability)
        if not policy:
            return False, "Autonomy policy violation or exhausted"

        autonomy = policy.get("autonomy", {})
        if not autonomy.get("enabled"):
            return False, "Autonomy policy violation or exhausted"

        scope = autonomy.get("scope", {})
        max_steps = scope.get("max_steps", 0)
        max_executions = scope.get("max_executions", 0)
        window = scope.get("time_window_seconds", 0)

        now = time.time()
        history = self._history.setdefault(capability, [])
        step_hist = self._step_history.setdefault(capability, set())

        if window:
            history[:] = [t for t in history if now - t <= window]
        if max_executions and len(history) >= max_executions:
            return False, "Autonomy policy violation or exhausted"

        step_id = context.get("step_id")
        if max_steps and step_id:
            if len(step_hist) >= max_steps and step_id not in step_hist:
                return False, "Autonomy policy violation or exhausted"

        return True, "ok"

    def consume_autonomy(self, capability: str, context: dict) -> None:
        now = time.time()
        history = self._history.setdefault(capability, [])
        history.append(now)
        step_id = context.get("step_id")
        if step_id:
            self._step_history.setdefault(capability, set()).add(step_id)
