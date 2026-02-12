# Agent Zero Architecture Map

This map outlines how **Agent Zero** executes tasks.  It focuses on the flow of messages through the agent loop, tool invocation, memory usage and logging.  Understanding this flow will help identify where to insert adapters when integrating into Billy.

## Agent execution pipeline

1. **Context creation**
   
   - When a user starts a session (via CLI or Web UI), Agent Zero constructs an `AgentContext`.  This object stores configuration, logs, memory pointers, subordinate agent information and metadata such as timestamps and unique IDs.

2. **Message loop**
   
   - The core loop lives in `agent.py`.  It is asynchronous and consists of repeated steps: assemble prompts, call the LLM, extract tool calls from the response, execute tools, update memory, and prepare the next prompt.  Extensions registered under `python/extensions/` can hook into each stage.

3. **Prompt assembly**
   
   - A system prompt (from `prompts/agent.system.main.md`) sets the overall behaviour.  Additional prompts (such as tool descriptions and memory summaries) are injected via extensions.  A chain of system messages, assistant messages and user messages is sent to the LLM.

4. **LLM call**
   
   - Agent Zero uses the configured model provider (via `models.py`) to call the LLM asynchronously.  Responses are streamed and can be interrupted by the user.

5. **Tool selection and execution**
   
   - After receiving a model response, Agent Zero extracts tool calls using JSON parsing.  Tools are looked up by name via the dynamic loader (`python/helpers/extract_tools.py`).  Each tool extends the `Tool` base class and implements `execute()`.  Tools may perform actions (running code, searching the web, delegating to sub‑agents) and emit their own logs.

6. **Memory read/write**
   
   - The memory subsystem, accessed via `python/helpers/memory.py`, provides vector‑store storage for fragments and solutions.  Extensions such as `_50_recall_memories.py` automatically retrieve relevant memories before the LLM call.  Tools like `memory_tool` allow agents to store and retrieve data explicitly.

7. **Logging and tracing**
   
   - Throughout the loop, Agent Zero emits structured log events.  The `Log` class records entries for prompts, tool calls and responses.  A `print_style` helper formats log output to the terminal.  Logs are saved to HTML files in the `logs/` folder for later inspection.

8. **Multi‑agent cooperation**
   
   - If a task is large or requires separate capabilities, the `call_subordinate` tool spawns a new `Agent` with its own context.  The parent agent awaits the subordinate’s result and integrates it into its reasoning.

## Architectural components

| Component | Role |
| --- | --- |
| **Agent** (`agent.py`) | Encapsulates the state and logic for a single agent instance.  Holds configuration, history, memory pointers and logs. |
| **AgentContext** (`agent.py`) | Tracks active agent instances and manages their lifecycle. |
| **Tool** base class (`python/helpers/tool.py`) | Defines the contract for all tools: initialization, execution and logging. |
| **Tool implementations** (`python/tools`) | Concrete tools used by the agent (code execution, memory access, subordinate agent creation, etc.). |
| **Tool loader** (`python/helpers/extract_tools.py`) | Dynamically imports tool classes and lists them for system prompts. |
| **Memory subsystem** (`python/helpers/memory.py`) | Provides vector‑store memory with FAISS, embedding models and summarisation. |
| **Extensions** (`python/extensions`) | Modules that hook into specific phases of the agent loop (before/after LLM calls, memory recall, tool execution, etc.). |
| **Logging** (`python/helpers/log.py`) | Records structured events, prints styled output and saves HTML logs. |
| **Configuration** (`models.py`, `prompts/`) | Defines model providers and prompt templates. |

## Diagram (textual)

```
┌─────────────┐           ┌─────────────┐           ┌──────────────┐
│ Client/UI   │───▶───▶──│ AgentContext│───▶───▶──│  Agent loop   │
└─────────────┘           └─────────────┘           └───────┬──────┘
                                                           │
                                                           ▼
                                ┌────────────────────────────┐
                                │ LLM call (models.py)       │
                                └────────────────────────────┘
                                                           │
                                                           ▼
                                ┌────────────────────────────┐
                                │ Tool invocation            │
                                └────────────────────────────┘
                                                           │
                                                           ▼
                                ┌────────────────────────────┐
                                │ Memory read/write          │
                                └────────────────────────────┘
                                                           │
                                                           ▼
                                ┌────────────────────────────┐
                                │ Logging & tracing          │
                                └────────────────────────────┘
```

Agent Zero’s loop contains multiple branches: after an LLM call, it may execute one or more tools, update memory and resume the loop.  Each step emits log events.  Extensions can inject additional behaviour at defined hook points.  The architecture is flexible but introduces coupling between tools, prompts and the agent loop.