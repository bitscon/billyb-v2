"""
Adapters that bridge Billy’s contracts to Agent Zero implementations.

These classes provide concrete implementations of the abstract interfaces
defined in `contracts.py`.  At this stage they are minimal and meant as
experiments rather than production‑ready code.  They demonstrate how to
import Agent Zero modules and expose their functionality through Billy’s
contracts.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import sys
from typing import Any, Dict, List, Optional

from .contracts import (
    ToolRegistry,
    ToolRunner,
    MemoryStore,
    TraceSink,
    AgentLoop,
    ToolSpec,
    TraceEvent,
)


def _ensure_agent_zero_path(a0_root: str) -> None:
    """Add Agent Zero's root and its ``python`` subdirectory to ``sys.path``.

    Agent Zero's repository uses a top‑level ``python`` package containing
    modules such as ``helpers`` and ``tools``.  In order to import modules
    like ``python.helpers.extract_tools``, Python must see the repository root
    on its search path so that ``python`` is a package.  We also add the
    ``python`` subdirectory itself so that modules can be imported without
    the ``python.`` prefix if needed.
    """
    # Insert the repository root so that the ``python`` package resolves
    if a0_root not in sys.path:
        sys.path.insert(0, a0_root)
    # Insert the inner python directory for convenience (helpers, tools, etc.)
    python_subdir = os.path.join(a0_root, "python")
    if python_subdir not in sys.path:
        sys.path.insert(0, python_subdir)


class AgentZeroToolRegistryAdapter(ToolRegistry):
    """Adapter that exposes Agent Zero’s tool definitions via the ToolRegistry interface."""

    def __init__(self, a0_root: str) -> None:
        self.a0_root = a0_root
        _ensure_agent_zero_path(a0_root)
        # Lazily loaded modules
        self._extract_tools = None  # type: ignore
        self._tool_base = None  # type: ignore
        self._tool_classes: Dict[str, type] = {}

    def _load_modules(self) -> None:
        """Import Agent Zero's tool loader and base class on demand."""
        if self._extract_tools is None or self._tool_base is None:
            try:
                self._extract_tools = importlib.import_module(
                    "python.helpers.extract_tools"
                )
                tool_module = importlib.import_module("python.helpers.tool")
                self._tool_base = getattr(tool_module, "Tool")
            except Exception as exc:
                # In environments where Agent Zero dependencies are missing (e.g. litellm),
                # degrade gracefully by providing stub implementations.  This allows
                # adapter code to function in limited mode without raising.
                # Store the error for debugging.
                self._import_error = exc
                # Provide a stub loader that returns no classes
                class _StubExtractor:
                    @staticmethod
                    def load_classes_from_folder(*args: Any, **kwargs: Any) -> List[type]:
                        return []

                self._extract_tools = _StubExtractor()
                # Use ``object`` as base class so every class check passes
                self._tool_base = object
                # Optionally print a warning; real logging system could be used
                # print(f"Warning: Agent Zero tool modules unavailable: {exc}")

    def _discover_tools(self) -> None:
        """Discover tool classes in Agent Zero’s `python/tools` directory."""
        if self._tool_classes:
            return
        self._load_modules()
        # folder path of Agent Zero tools
        tools_path = os.path.join(self.a0_root, "python", "tools")
        # Use the helper function to load classes that subclass Tool
        classes = self._extract_tools.load_classes_from_folder(
            tools_path, "*.py", self._tool_base, one_per_file=True
        )
        for cls in classes:
            name = getattr(cls, "__name__", cls.__class__.__name__)
            self._tool_classes[name.lower()] = cls

    async def list_tools(self) -> List[ToolSpec]:
        self._discover_tools()
        specs: List[ToolSpec] = []
        for name, cls in self._tool_classes.items():
            description = inspect.getdoc(cls) or f"No description for {name}"
            # Inspect the execute signature for argument names
            args_schema: Dict[str, Any] = {}
            try:
                sig = inspect.signature(cls.execute)
                for param in sig.parameters.values():
                    if param.name in ("self", "**kwargs"):
                        continue
                    # Use annotation if available, else default to str
                    ann = (
                        param.annotation.__name__ if hasattr(param.annotation, "__name__") else str(param.annotation)
                    )
                    args_schema[param.name] = {"type": ann or "str"}
            except Exception:
                pass
            specs.append(
                ToolSpec(
                    name=name,
                    description=description.strip(),
                    args_schema=args_schema,
                    permissions=[],
                )
            )
        return specs

    async def get_schema(self, tool_name: str) -> Optional[ToolSpec]:
        tool_name = tool_name.lower()
        tools = await self.list_tools()
        for spec in tools:
            if spec.name.lower() == tool_name:
                return spec
        return None

    async def invoke_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """
        Invoke a tool using Agent Zero’s implementation.

        Note: This stub implementation simply instantiates the tool class and
        calls its `execute` method with no agent context.  Most Agent Zero tools
        expect an `Agent` instance and additional parameters, so this should
        be replaced with a proper integration during Phase 4.  Until then, this
        method returns a message indicating the call would occur.
        """
        self._discover_tools()
        cls = self._tool_classes.get(tool_name.lower())
        if not cls:
            raise ValueError(f"Tool '{tool_name}' not found")
        # Create a dummy tool instance (agent=None, method=None, loop_data=None)
        # Note: The constructor signature is (agent, name, method, args, message, loop_data, **kwargs).
        try:
            # Provide minimal required arguments.  The agent is None for now.
            tool_instance = cls(
                agent=None,
                name=tool_name,
                method=None,
                args=args,
                message="",
                loop_data=None,
            )
            if asyncio.iscoroutinefunction(tool_instance.execute):
                result = await tool_instance.execute(**args)
            else:
                # Synchronous execution
                result = tool_instance.execute(**args)
            return result
        except Exception as exc:
            # If execution fails, return a stub result describing the invocation
            return {
                "error": str(exc),
                "message": f"Invoked tool '{tool_name}' with args {args} (stub)",
            }


class AgentZeroMemoryAdapter(MemoryStore):
    """Adapter that wraps Agent Zero’s memory subsystem.

    This adapter provides a simplified interface over the complex memory system
    present in Agent Zero.  For demonstration purposes it uses an in‑memory
    dictionary as a fallback when the actual memory API is unavailable.  In
    production, this should delegate to `python.helpers.memory.Memory` methods.
    """

    def __init__(self, a0_root: str, memory_subdir: str = "billy") -> None:
        self.a0_root = a0_root
        self.memory_subdir = memory_subdir
        _ensure_agent_zero_path(a0_root)
        # Fallback simple store: {key: (value, tags)}
        self._store: Dict[str, Any] = {}
        self._tags: Dict[str, List[str]] = {}
        # TODO: integrate with Agent Zero memory API when available

    async def write(self, key: str, value: Any, tags: Optional[List[str]] = None) -> None:
        self._store[key] = value
        self._tags[key] = tags or []

    async def query(self, query: str, *, k: int = 5) -> List[Dict[str, Any]]:
        """Very naive in‑memory query that returns up to `k` entries whose keys contain the query."""
        results: List[Dict[str, Any]] = []
        for key, value in self._store.items():
            if query.lower() in key.lower():
                results.append(
                    {
                        "key": key,
                        "value": value,
                        "tags": self._tags.get(key, []),
                        "score": 1.0,
                    }
                )
            if len(results) >= k:
                break
        return results

    async def summarize(self, entries: List[Dict[str, Any]]) -> str:
        """Concatenate values and truncate for now.  Replace with summarisation model in future."""
        if not entries:
            return ""
        combined = "\n".join(str(e.get("value", "")) for e in entries)
        return combined[:500]  # limit length to prevent blowing up prompts


class AgentZeroTraceAdapter(TraceSink):
    """Simple trace sink that collects events in memory and prints them on flush."""

    def __init__(self) -> None:
        self._events: List[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self._events.append(event)

    async def flush(self) -> None:
        for ev in self._events:
            print(f"[{ev.timestamp}] {ev.agent_id} {ev.type}: {ev.data}")
        self._events.clear()


class AgentZeroPlannerAdapter(AgentLoop):
    """Experimental adapter that delegates planning to Agent Zero’s agent loop.

    This adapter is largely a placeholder.  It demonstrates how one might call
    into Agent Zero’s agent implementation but does not provide a full
    integration.  Use this adapter for A/B experiments only.
    """

    def __init__(self, a0_root: str, persona: str = "default") -> None:
        self.a0_root = a0_root
        self.persona = persona
        _ensure_agent_zero_path(a0_root)
        try:
            self._agent_module = importlib.import_module("agent")
        except Exception as exc:
            raise RuntimeError(f"Failed to import Agent module from Agent Zero: {exc}")

    async def run(self, user_input: str, *, persona: str) -> str:
        """Invoke Agent Zero’s agent loop for a single turn and return its response."""
        # NOTE: This stub implementation simply returns a canned response.  A real
        # implementation would instantiate an AgentContext, assemble prompts and
        # run the loop.
        return f"[AgentZeroPlannerAdapter] Received input: '{user_input}' for persona '{persona}'"

    async def register_tool_call(self, tool_name: str, args: Dict[str, Any]) -> None:
        # For now, just log the intent.  Real implementation would record this for gating.
        print(f"Planning to call tool {tool_name} with args {args}")