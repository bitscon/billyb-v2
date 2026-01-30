"""
Evaluation harness for the Billy↔Agent Zero integration.

This script exercises the adapter layer to validate core functionality and
collects metrics for further analysis.  It is intended as a lightweight
behavioural evaluation (Phase 5.5) and should be expanded with real LLM
interactions once available.  The script does not perform any network
operations and can run in constrained environments.

Three scenarios are tested:

1. **Tool invocation** — calls a known tool via the runner and prints the result.
2. **Memory operations** — writes a key/value pair and queries it back.
3. **Adversarial invocation** — attempts to call a tool with invalid arguments
   and catches the resulting error.

At the end, the script prints a summary of metrics collected via the
``observability`` module (if available).

Run this module directly to perform the evaluation:

```
python -m evaluation.evaluate_integration
```
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from adapter_impl.agentzero_adapter import (
    AgentZeroToolRegistryAdapter,
    AgentZeroMemoryAdapter,
    AgentZeroTraceAdapter,
)
from adapter_impl.tool_runner import LocalToolRunner
from adapter_impl.observability import get_metrics, register_tool_run  # type: ignore


async def evaluate() -> None:
    """Run a series of integration tests and print the results."""
    a0_root = "agent-zero-main"
    registry = AgentZeroToolRegistryAdapter(a0_root)
    memory = AgentZeroMemoryAdapter(a0_root)
    trace = AgentZeroTraceAdapter()
    runner = LocalToolRunner(registry, trace)

    print("\n=== Evaluation Start ===\n")

    # Scenario 1: Tool invocation
    print("Scenario 1: Tool invocation")
    tools = await registry.list_tools()
    if tools:
        # Use the first available tool as a smoke test
        spec = tools[0]
        tool_name = spec.name
        # Generate dummy arguments based on schema: use empty or simple values
        args: Dict[str, Any] = {}
        for field, ftype in spec.args_schema.items():
            # Provide a string for string fields, integer for numbers, etc.
            if ftype in ("string", "str", "text"):
                args[field] = "hello"
            elif ftype in ("int", "integer", "number"):
                args[field] = 1
            elif ftype in ("float",):
                args[field] = 0.0
            else:
                args[field] = None
        try:
            result = await runner.execute(tool_name, args, use_docker=False)
            print(f"Invoked tool '{tool_name}' with args {args}; result: {result}\n")
        except Exception as exc:
            print(f"Error invoking tool '{tool_name}': {exc}\n")
    else:
        print("No tools discovered; skipping tool invocation test.\n")

    # Scenario 2: Memory operations
    print("Scenario 2: Memory operations")
    try:
        await memory.write("greeting", "hello world", tags=["eval"])
        query_res = await memory.query("greet")
        print(f"Memory query returned: {query_res}")
        summary = await memory.summarize(query_res)
        print(f"Memory summary: {summary}\n")
    except Exception as exc:
        print(f"Memory operations failed: {exc}\n")

    # Scenario 3: Adversarial invocation
    print("Scenario 3: Adversarial invocation")
    try:
        await runner.execute("nonexistenttool", {}, use_docker=False)
    except Exception as exc:
        print(f"Expected error for unknown tool: {exc}\n")

    # Flush trace events (prints to stdout by default)
    await trace.flush()

    # Print metrics if available
    try:
        metrics = get_metrics()  # type: ignore[attr-defined]
        print("Metrics snapshot:")
        for key, value in metrics.items():
            print(f"- {key}: {value}")
    except Exception:
        print("Prometheus metrics not available or get_metrics not defined.\n")

    print("=== Evaluation Complete ===\n")


if __name__ == "__main__":
    asyncio.run(evaluate())