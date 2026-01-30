"""
ToolRunner implementation that executes tools inside Docker containers.

The DockerToolRunner is responsible for running a tool image with
appropriate arguments, enforcing resource constraints and network
policies.  This implementation is a stub to illustrate the
integration pattern; it does not actually call Docker unless the
``docker`` CLI is available.  In production, this runner would
construct a proper ``docker run`` command, mount the workspace,
configure seccomp and cgroups, and capture stdout/stderr.

Usage:

```python
from adapter_impl.agentzero_adapter import AgentZeroToolRegistryAdapter
from adapter_impl.docker_runner import DockerToolRunner

registry = AgentZeroToolRegistryAdapter(a0_root="/path/to/agent-zero")
runner = DockerToolRunner(registry, image_map={"notifyusertool": "mytool-image:latest"})
result = await runner.execute("notifyusertool", {"message": "hello"}, use_docker=True)
```

Until Docker integration is implemented, calling ``execute`` with
``use_docker=True`` will raise ``NotImplementedError``.  You can
still call with ``use_docker=False`` to fall back to a local execution
via the underlying registry.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from typing import Any, Dict, Optional

from .contracts import ToolRunner, ToolRegistry, TraceSink, TraceEvent
from .observability import register_tool_run


class DockerToolRunner(ToolRunner):
    """Run tools either locally or inside Docker containers.

    Args:
        registry: Tool registry used to resolve and invoke tools locally.
        trace_sink: Optional trace sink to emit execution events.
        image_map: Mapping from tool names to Docker image names.  If a tool
            name is not present, the runner will construct an image name by
            lower‑casing the tool name.
        workspace: Host directory to mount into the container at `/workspace`.
        default_limits: Default resource limits passed to Docker (e.g. CPU, memory).
    """

    def __init__(
        self,
        registry: ToolRegistry,
        trace_sink: Optional[TraceSink] = None,
        image_map: Optional[Dict[str, str]] = None,
        workspace: Optional[str] = None,
        default_limits: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.registry = registry
        self.trace_sink = trace_sink
        self.image_map = image_map or {}
        self.workspace = workspace or os.getcwd()
        self.default_limits = default_limits or {}

    async def execute(self, tool_name: str, args: Dict[str, Any], *, use_docker: bool = False) -> Any:
        """Execute a tool, optionally within a Docker container.

        When ``use_docker`` is True, this stub raises ``NotImplementedError`` to
        indicate that Docker integration is not yet implemented.  Otherwise,
        it delegates to the underlying registry.
        """
        if use_docker:
            # Compose image name
            image = self.image_map.get(tool_name.lower(), f"{tool_name.lower()}:latest")
            # Currently we do not perform actual Docker execution; raise for now
            raise NotImplementedError(
                f"Docker execution for tool '{tool_name}' is not yet implemented. Intended image: {image}"
            )
        # Fallback: delegate to the registry (local execution)
        return await self.registry.invoke_tool(tool_name, args)

    async def set_policy(self, resource_limits: Dict[str, Any], network_policy: str) -> None:
        # Store default limits; enforcement would occur when constructing the docker command
        self.default_limits = dict(resource_limits or {})
        # We ignore network_policy for now; a real implementation would use it to set
        # Docker's network mode or iptables rules