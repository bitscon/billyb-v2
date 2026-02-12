# Agent Zero Inventory

This document summarises the key components of the **agent‑zero‑main** repository (as provided) to help guide reuse decisions.  Agent Zero is a mature framework with many features; this inventory focuses on elements most relevant to Billy integration.

## Runtime entrypoints

- **CLI and Web UI launchers**

  - `run_cli.py` and `run_ui.py` are the primary launchers.  Both spin up an `AgentContext` and enter an asynchronous message loop.  The UI variant starts a web server, while the CLI variant interacts via the terminal.

- **Core agent implementation – `agent.py`**

  The `Agent` class and `AgentContext` provide the core agent loop.  Agents maintain conversation history, use prompts and tools to reason about tasks, and can spawn subordinate agents for delegation.  The loop is asynchronous, streaming intermediate reasoning and tool output.

## Tool system

- **Tool base class** – `python/helpers/tool.py`
  
  Provides the abstract `Tool` class with `execute()` and `before_execution`/`after_execution` hooks.  Tools receive an `Agent` instance, name, method and argument dictionary.  After execution, tool results are logged and recorded in history.

- **Built‑in tools** – `python/tools/*`
  
  Agent Zero ships with a suite of built‑in tools such as:
  
  | Tool | Function |
  | --- | --- |
  | `behavior_adjustment` | Modify the agent’s behaviour mid‑run. |
  | `call_subordinate` | Spawn subordinate agents for task decomposition. |
  | `code_execution_tool` | Execute Python, Node.js and shell code safely. |
  | `input` | Prompt for user input in the terminal. |
  | `response_tool` | Format responses to the user. |
  | `memory_tool` | Save, load and delete data from the memory subsystem. |
  
  Tools are discovered dynamically: each file in the `python/tools` folder defines a class that subclasses `Tool`.  Agent Zero uses helper functions (`python/helpers/extract_tools.py`) to import these classes and list them for the system prompt.  Tools expose their argument schema and description via dedicated prompt files in the `prompts/` directory.

## Tool execution / sandboxing

Agent Zero distinguishes between tool **registration** and tool **execution**.  Registration defines the schema and metadata; execution occurs in either the local process or an isolated environment.  The `code_execution_tool` can run code within a sandboxed shell or Python environment.  For containerisation, the `python/helpers/docker.py` module encapsulates Docker interactions, providing functions to build images, run containers with resource limits and capture outputs.

## Memory subsystem

- **Vector‑store memory** – `python/helpers/memory.py`
  
  Agent Zero stores knowledge fragments, solutions and other artefacts in a vector database backed by FAISS.  Memory entries are summarised and embedded using LangChain embedding models.  The memory API supports writing data, querying by similarity and reloading memory contexts.  A separate consolidation module (`python/helpers/memory_consolidation.py`) periodically summarises and compresses old memories.

- **Memory tools** – `memory_tool` uses the memory subsystem to allow agents to save and recall data during a conversation.

## Prompt and extension system

Agent Zero is heavily prompt‑driven.  The `prompts/` folder contains system and tool prompt templates.  The framework also includes a plug‑in extension mechanism under `python/extensions/` that lets developers hook into various phases of the agent loop (e.g., before/after LLM calls, tool execution, message history updates).  These extensions implement cross‑cutting concerns such as logging, secret masking, memory recall and UI updates.

## Logging and tracing

- **Structured logging** – `python/helpers/log.py` and `python/helpers/print_style.py` provide a hierarchical log format.  Each agent context maintains a log which records messages, tool calls, and events.  Logs are streamed to the terminal and saved as HTML in the `logs/` directory.

- **Event system** – Many components emit structured events that include metadata such as timestamps, agent IDs, tool names and durations.  This event format can power debugging UIs.

## Multi‑agent orchestration

Agent Zero supports hierarchical agents.  Agents can spawn subordinate agents via the `call_subordinate` tool, passing along context and instructions.  Subordinate agents operate with their own memory and prompts but report results back to their parent agent.  This allows complex tasks to be decomposed into smaller parts.

## External integrations

- **Knowledge search** – `python/helpers/duckduckgo_search.py` and `python/helpers/searxng.py` integrate web search services.
- **Communication** – `python/helpers/email_client.py` and other utilities enable email interactions.
- **Hardware/runtime** – `python/helpers/docker.py`, `python/helpers/process.py` and `python/helpers/shell_*` modules handle local and remote command execution.

## Summary

Agent Zero is a comprehensive agentic framework with its own tool registry, vector‑store memory, extension hooks, multi‑agent orchestration and robust logging.  For Billy integration, the most relevant areas are the **tool system**, **memory subsystem**, **logging/tracing patterns** and the **planner/agent loop**.  Reusing these can accelerate Billy’s evolution from a simple chat wrapper to a full‑featured agent platform.