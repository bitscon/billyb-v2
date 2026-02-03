from core.contracts.loader import ContractViolation

class StepExecutor:
    """
    Executes exactly one plan step after explicit approval.
    """

    def execute_step(self, plan: dict, step_id: str, tool_registry, docker_runner, trace_id: str):
        steps = plan.get("steps", [])
        step = next((s for s in steps if s["step_id"] == step_id), None)

        if not step:
            raise ContractViolation(f"Step not found: {step_id}")

        tool_id = step.get("tool_id")
        if not tool_id:
            raise ContractViolation("Step has no tool_id")

        spec = tool_registry.get(tool_id)

        return docker_runner.run(
            tool_spec=spec,
            image=spec.get("image", "billy-hello"),
            args=step.get("args", []),
            trace_id=trace_id,
        )
