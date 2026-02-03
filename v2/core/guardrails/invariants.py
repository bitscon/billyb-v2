from core.contracts.loader import ContractViolation

def assert_trace_id(trace_id: str):
    if not trace_id or not isinstance(trace_id, str):
        raise ContractViolation("Missing or invalid trace_id")

def assert_no_tool_execution_without_registry(tool_id: str, registry):
    try:
        registry.get(tool_id)
    except Exception:
        raise ContractViolation(f"Tool executed without registry entry: {tool_id}")

def assert_explicit_memory_write(user_input: str):
    if "remember" in user_input.lower() and not user_input.lower().startswith("remember:"):
        raise ContractViolation("Implicit memory write attempt detected")
