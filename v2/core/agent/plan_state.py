from v2.core.contracts.loader import ContractViolation

class PlanState:
    """
    Tracks execution state of a single plan.
    """

    def __init__(self, plan: dict):
        self.plan_id = plan["plan_id"]
        self.steps = {s["step_id"]: "pending" for s in plan.get("steps", [])}
        self.paused = False
        self.aborted = False

    def can_execute(self, step_id: str):
        if self.aborted:
            raise ContractViolation("Plan is aborted")
        if self.paused:
            raise ContractViolation("Plan is paused")
        if self.steps.get(step_id) != "pending":
            raise ContractViolation(f"Step not executable: {step_id}")

    def mark_running(self, step_id: str):
        self.steps[step_id] = "running"

    def mark_done(self, step_id: str):
        self.steps[step_id] = "done"

    def mark_failed(self, step_id: str):
        self.steps[step_id] = "failed"

    def pause(self):
        self.paused = True

    def abort(self):
        self.aborted = True
