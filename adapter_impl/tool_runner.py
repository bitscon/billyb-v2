"""
ToolRunner implementations for Billy.

These classes provide concrete implementations of the :class:`ToolRunner` interface
defined in ``contracts.py``.  A ToolRunner is responsible for executing a
named tool with a set of arguments and returning its result.  The runner
enforces any execution policies (such as whether to use Docker) and may emit
trace events via a :class:`TraceSink`.

The initial implementation provided here runs tools directly in the current
process by delegating to the configured :class:`ToolRegistry`.  It does not
support containerised execution yet; instead, requests to run a tool with
``use_docker=True`` will raise ``NotImplementedError``.  This design
encapsulates the execution policy decision and prepares the codebase for
future integration with Docker or other sandboxes.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from .contracts import ToolRegistry, ToolRunner, TraceSink, TraceEvent

# Try to import observability functions.  If unavailable (e.g. during tests),
# fallback to no‑ops.  We import at module load so that tools can update
# metrics without knowing whether prometheus_client is installed.
try:
    from .observability import register_tool_run
except Exception:
    # define a no‑op fallback
    def register_tool_run(tool: str, status: str, duration: float) -> None:  # type: ignore
        pass


class LocalToolRunner(ToolRunner):
    """Execute tools synchronously in the current Python process.

    This runner relies on a supplied :class:`ToolRegistry` to discover and
    invoke tool implementations.  When a trace sink is provided, each tool
    invocation emits a ``TraceEvent`` upon completion.  The runner does not
    isolate tool executions—errors or side effects propagate directly back to
    the caller.  It therefore should only be used in trusted or development
    environments.

    Args:
        registry: The registry used to resolve tool names to implementations.
        trace_sink: Optional sink for emitting trace events about tool
            execution.  If provided, an event is emitted after each call.
    """

    def __init__(self, registry: ToolRegistry, trace_sink: Optional[TraceSink] = None) -> None:
        self._registry = registry
        self._trace_sink = trace_sink
        self._resource_limits: Dict[str, Any] = {}
        self._network_policy: str = "allow"

    async def execute(
        self, tool_name: str, args: Dict[str, Any], *, use_docker: bool = False
    ) -> Any:
        """Execute a tool via the underlying registry.

        If ``use_docker`` is True, this implementation will raise
        ``NotImplementedError`` as containerised execution is not yet
        supported.  Otherwise it delegates to ``ToolRegistry.invoke_tool``.

        After execution, if a trace sink is configured, a ``tool_result``
        event is emitted containing the result.  Errors raised by the tool
        invocation are propagated to the caller.
        """
        if use_docker:
            raise NotImplementedError(
                "LocalToolRunner does not support Docker execution yet; please set use_docker=False"
            )
        # Invoke the tool via registry
        start_time = time.time()
        status = "ok"
        result: Any = None
        result_exc: Exception | None = None
        try:
            result = await self._registry.invoke_tool(tool_name, args)
        except Exception as exc:
            status = "error"
            result_exc = exc
        duration = time.time() - start_time
        # Record metrics (tool name in lower case for consistency)
        try:
            register_tool_run(tool_name.lower(), status, duration)
        except Exception:
            pass
        # Emit trace if sink exists
        if self._trace_sink is not None:
            event = TraceEvent(
                timestamp=time.time(),
                agent_id="tool_runner",
                type="tool_result",
                data={
                    "tool": tool_name,
                    "args": args,
                    "result": result,
                    "duration": duration,
                    "status": status,
                },
            )
            await self._trace_sink.emit(event)
        if status == "error" and result_exc is not None:
            raise result_exc
        return result

    async def set_policy(self, resource_limits: Dict[str, Any], network_policy: str) -> None:
        """Update execution policies for the runner.

        The ``resource_limits`` dictionary may contain keys such as
        ``cpu``, ``memory``, ``timeout``, etc.  ``network_policy`` should
        be either ``"allow"`` or ``"deny"`` to control external network
        access.  These policies are advisory only; this implementation does
        not enforce them but stores them for future use.
        """
        self._resource_limits = dict(resource_limits or {})
        self._network_policy = network_policy
