"""
Contracts defining the interfaces between Billy and adapter implementations.

These interfaces mirror the contracts documented in the integration plan.  They are
designed to be asynchronous so that adapters can perform I/O (such as
loading Agent Zero modules, calling external services or running Docker
containers) without blocking the event loop.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import abc
import asyncio


@dataclass
class ToolSpec:
    """Metadata describing a tool.

    Args:
        name: The canonical name of the tool.
        description: A human‑readable description.
        args_schema: A dictionary describing argument names and types.  This can
            follow a JSON‑schema–like structure.
        permissions: A list of strings indicating required permissions, such as
            "network", "filesystem" or "secrets".
    """
    name: str
    description: str
    args_schema: Dict[str, Any]
    permissions: List[str]


class ToolRegistry(abc.ABC):
    """Interface for discovering tools and retrieving their metadata."""

    @abc.abstractmethod
    async def list_tools(self) -> List[ToolSpec]:
        """Return metadata for all available tools."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_schema(self, tool_name: str) -> Optional[ToolSpec]:
        """Return the ToolSpec for a single tool."""
        raise NotImplementedError

    @abc.abstractmethod
    async def invoke_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Invoke a tool and return its output.

        Tool invocation may be asynchronous if it involves I/O.  The return type
        is left as Any to accommodate different tool result structures.
        """
        raise NotImplementedError


class ToolRunner(abc.ABC):
    """Interface responsible for executing tools in the correct environment."""

    @abc.abstractmethod
    async def execute(
        self, tool_name: str, args: Dict[str, Any], *, use_docker: bool = False
    ) -> Any:
        """Run the specified tool with arguments.

        When `use_docker` is True, the tool should be executed inside a Docker
        container; otherwise, it may run locally.  Implementations must enforce
        resource limits and security policies as appropriate.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def set_policy(self, resource_limits: Dict[str, Any], network_policy: str) -> None:
        """Configure default resource limits and network policies."""
        raise NotImplementedError


class MemoryStore(abc.ABC):
    """Interface for storing and retrieving conversational memory."""

    @abc.abstractmethod
    async def write(self, key: str, value: Any, tags: Optional[List[str]] = None) -> None:
        """Persist a value under a key with optional tags."""
        raise NotImplementedError

    @abc.abstractmethod
    async def query(self, query: str, *, k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the `k` most relevant entries to the query.

        Returned items should include the stored value and metadata such as
        similarity scores, timestamps and tags.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def summarize(self, entries: List[Dict[str, Any]]) -> str:
        """Produce a compact summary of multiple entries for inclusion in prompts."""
        raise NotImplementedError


@dataclass
class TraceEvent:
    """Represents a structured event emitted during agent execution."""
    timestamp: float
    agent_id: str
    type: str
    data: Dict[str, Any]


class TraceSink(abc.ABC):
    """Interface for emitting structured trace events."""

    @abc.abstractmethod
    async def emit(self, event: TraceEvent) -> None:
        """Record a trace event."""
        raise NotImplementedError

    @abc.abstractmethod
    async def flush(self) -> None:
        """Flush buffered events to persistent storage (if any)."""
        raise NotImplementedError


class AgentLoop(abc.ABC):
    """Interface representing the high‑level agent reasoning loop."""

    @abc.abstractmethod
    async def run(self, user_input: str, *, persona: str) -> str:
        """Given a user input and persona, return a response.

        Implementations may call tools, memory and emit trace events.  The loop
        should return the final answer to the caller.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def register_tool_call(self, tool_name: str, args: Dict[str, Any]) -> None:
        """Record that the loop decided to call a tool for auditing and gating."""
        raise NotImplementedError