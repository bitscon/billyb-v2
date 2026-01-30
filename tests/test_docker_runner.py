"""
Integration tests for the DockerToolRunner.

These tests exercise the behaviour of the ``DockerToolRunner`` implementation
defined in ``adapter_impl.docker_runner``.  The runner is responsible for
delegating tool execution either locally via the underlying registry or,
optionally, inside a Docker container.  Because Docker integration is not
implemented yet, requests with ``use_docker=True`` should raise
``NotImplementedError``.  When ``use_docker`` is false, the runner should
behave like the ``LocalToolRunner`` and delegate to the registry.  The
tests below verify these behaviours and ensure that policy updates are stored
without raising errors.

The test suite intentionally relies only on builtin ``unittest`` to avoid
additional dependencies.  Each test case is asynchronous to mirror the
adapter interfaces.
"""

import unittest

from adapter_impl.agentzero_adapter import AgentZeroToolRegistryAdapter
from adapter_impl.docker_runner import DockerToolRunner


class TestDockerToolRunner(unittest.IsolatedAsyncioTestCase):
    """Integration tests for the DockerToolRunner implementation."""

    async def asyncSetUp(self) -> None:
        """Initialise a registry and runner for each test."""
        self.a0_root = "agent-zero-main"
        self.registry = AgentZeroToolRegistryAdapter(self.a0_root)
        self.runner = DockerToolRunner(self.registry)

    async def test_raises_when_use_docker_true(self) -> None:
        """Calling execute with use_docker=True should raise NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            await self.runner.execute("notifyusertool", {"message": "hi"}, use_docker=True)

    async def test_fallback_to_local_execution(self) -> None:
        """When use_docker=False, execution should delegate to the registry."""
        # Unknown tool should raise ValueError (propagated from registry)
        with self.assertRaises(ValueError):
            await self.runner.execute("nonexistenttool", {}, use_docker=False)
        # Known tool may or may not exist depending on installed dependencies.  If the
        # registry does not know about the tool, it should raise ValueError.  Otherwise,
        # the call should succeed and return a non-None result.
        try:
            result = await self.runner.execute("notifyusertool", {"message": "hello"}, use_docker=False)
            # If no exception is raised, assert that a result object is returned
            self.assertIsNotNone(result)
        except ValueError:
            # Acceptable outcome if registry cannot resolve the tool
            pass

    async def test_policy_update_stores_limits(self) -> None:
        """Updating execution policies should store limits without error."""
        limits = {"cpu": 1, "memory": "128m", "timeout": 5}
        await self.runner.set_policy(limits, network_policy="deny")
        # Check that limits were stored on the runner instance
        self.assertEqual(self.runner.default_limits.get("cpu"), 1)
        self.assertEqual(self.runner.default_limits.get("memory"), "128m")
        self.assertEqual(self.runner.default_limits.get("timeout"), 5)


if __name__ == "__main__":
    unittest.main()