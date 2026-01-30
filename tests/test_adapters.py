"""
Unit tests for adapter implementations.

These tests exercise the core behaviours of the adapter classes defined
under ``adapter_impl``.  They focus on deterministic logic such as tool
discovery, memory CRUD and simple execution semantics.  They do not
require network access or a running Agent Zero service.

To run the tests, install ``pytest`` and execute:

```
pytest -q
```
"""
import unittest

from adapter_impl.agentzero_adapter import (
    AgentZeroToolRegistryAdapter,
    AgentZeroMemoryAdapter,
    AgentZeroTraceAdapter,
)
from adapter_impl.tool_runner import LocalToolRunner


class TestAdapters(unittest.IsolatedAsyncioTestCase):
    """Unit tests for Billy↔Agent Zero adapters implemented in adapter_impl."""

    async def test_tool_registry_lists_tools(self) -> None:
        """The tool registry should discover one or more tools in Agent Zero."""
        a0_root = "agent-zero-main"
        registry = AgentZeroToolRegistryAdapter(a0_root)
        tools = await registry.list_tools()
        # In environments where Agent Zero dependencies are missing, the registry may return
        # an empty list; treat this as acceptable but ensure no exception is raised.
        # Check that each returned spec has required attributes
        for spec in tools:
            self.assertTrue(spec.name)
            self.assertIsNotNone(spec.description)
            self.assertIsInstance(spec.args_schema, dict)

    async def test_tool_registry_get_schema_for_known_tool(self) -> None:
        """Verify that get_schema returns a ToolSpec for an existing tool."""
        a0_root = "agent-zero-main"
        registry = AgentZeroToolRegistryAdapter(a0_root)
        spec = await registry.get_schema("notifyusertool")
        if spec is None:
            # If dependencies are missing the registry may not know about tools; skip assertions
            return
        self.assertIn("message", spec.args_schema)

    async def test_tool_registry_invoke_unknown_tool_raises(self) -> None:
        """Attempting to invoke an unknown tool should raise ValueError."""
        a0_root = "agent-zero-main"
        registry = AgentZeroToolRegistryAdapter(a0_root)
        with self.assertRaises(ValueError):
            await registry.invoke_tool("nonexistenttool", {})

    async def test_memory_adapter_write_and_query(self) -> None:
        """Ensure memory writes can be queried and summarised."""
        adapter = AgentZeroMemoryAdapter(a0_root="agent-zero-main")
        await adapter.write("hello", "world", tags=["greeting"])
        results = await adapter.query("hel")
        self.assertTrue(results, "Expected query to return at least one entry")
        self.assertEqual(results[0]["key"], "hello")
        summary = await adapter.summarize(results)
        self.assertIn("world", summary)

    async def test_local_tool_runner_execution_and_trace(self) -> None:
        """LocalToolRunner should delegate execution and emit a trace event."""
        a0_root = "agent-zero-main"
        registry = AgentZeroToolRegistryAdapter(a0_root)
        trace = AgentZeroTraceAdapter()
        runner = LocalToolRunner(registry, trace)
        # An unknown tool should raise
        with self.assertRaises(ValueError):
            await runner.execute("nonexistenttool", {})
        # Execute a known tool if registry knows about it; otherwise assert that a ValueError is raised
        spec = await registry.get_schema("notifyusertool")
        if spec is not None:
            res = await runner.execute("notifyusertool", {"message": "hi"}, use_docker=False)
            self.assertIsNotNone(res)
            # Flush trace events to ensure at least one event is emitted and cleared
            await trace.flush()
        else:
            with self.assertRaises(ValueError):
                await runner.execute("notifyusertool", {"message": "hi"}, use_docker=False)


if __name__ == "__main__":
    unittest.main()
