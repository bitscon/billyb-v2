# Billy v2 Architecture Map

This document maps out the current architecture of **Billy v2**, focusing on the execution pipeline and key boundaries.  It serves as a starting point for defining integration seams where Agent Zero components could plug in.

## Agent execution pipeline

1. **Request arrives**
   
   - **CLI**: The user runs `python main.py "<prompt>"`.  The script forwards the prompt to `BillyRuntime.ask()` and prints the result.
   - **API**: A client sends a POST request to `/ask` (or `/v1/chat/completions`), containing a user message.  The FastAPI handler calls `BillyRuntime.ask()` and wraps the response in a JSON payload.
   
2. **Runtime initialization**
   
   - When `BillyRuntime` is constructed (once per process), it loads `config.yaml` to determine which LLM provider to call and loads the canonical charter from `docs/charter/`.  It also sets the `mode` to `ADVISORY` by default.

3. **System prompt assembly**
   
   - When `ask()` is invoked, the runtime checks whether the input is a mode‑switch command.  If not, it builds a **system prompt** consisting of:
     - Current operational mode (Advisory or Operator).
     - A deterministic identity statement (`"I am Billy — a digital Farm Hand…"`).
     - The full charter text.

4. **LLM call**
   
   - The runtime calls `core/llm_api.py:get_completion()` with the system prompt and user message.  This helper inspects the configuration to pick a provider (OpenAI, OpenRouter, Ollama), fetches API keys from configuration or environment, and invokes the provider’s chat completion API.  The call is synchronous.

5. **Post‑processing**
   
   - After receiving the LLM’s answer, `_identity_guard()` checks whether the answer leaks forbidden identity phrases (e.g., “I’m an AI”).  If so, the response is overridden with the deterministic identity.  It also responds deterministically to identity questions.
   - The final text is returned to the caller.

6. **Memory operations (API only)**

   - If MongoDB is configured, `api.py` exposes endpoints to store (`memory_put`) and retrieve (`memory_get`) arbitrary key/value pairs in the `memory` collection.  These endpoints are not used by the runtime itself; they must be called explicitly by clients.

## Boundaries and seams

| Boundary | Current state | Potential integration | Notes |
| --- | --- | --- | --- |
| **Tool invocation** | None.  Billy has no concept of tools or actions. | Introduce a `ToolRegistry` and `ToolRunner` so that prompts can call tools.  Agent Zero’s tool discovery and execution patterns can inform this design. | Requires designing a schema and API for tools and adding adapters to call Agent Zero tools. |
| **Memory subsystem** | Optional Mongo key/value store; no context retrieval during conversations. | Replace or augment with a vector‑store memory (FAISS) via a `MemoryStore` interface.  Use Agent Zero’s memory subsystem behind an adapter. | Must handle embedding models and ensure per‑persona isolation. |
| **Trace/logging** | Basic `print()` statements; no structured events. | Introduce a `TraceSink` that emits structured events (tool calls, LLM calls, memory operations).  Agent Zero’s logging pattern can be adapted. | Improves debuggability and paves the way for a UI. |
| **Agent loop** | Single LLM call per request; no planning or tool selection loops. | Maintain Billy as the orchestrator but optionally use Agent Zero’s planner as a strategy module invoked through an adapter (Phase 4.3). | Avoid wholesale replacement; start with optional experiments. |
| **Execution environment** | LLM calls occur in‑process; there is no sandbox for user‑defined code or tools. | Implement a `DockerRunner` to run tools in isolated containers.  Agent Zero’s Docker helpers can guide design. | Will require Docker on the host and careful security policies. |

## Diagram (textual)

```
┌─────────────┐      ┌──────────────────┐      ┌─────────────┐
│  Client/UI  │───▶│  Billy API/CLI   │───▶│ BillyRuntime │
└─────────────┘      └──────────────────┘      └───────┬─────┘
                                                     │
                                                     ▼
                                        ┌───────────────────────┐
                                        │  LLM Provider (OpenAI, │
                                        │   Ollama, etc.)        │
                                        └───────────────────────┘
```

At present, there are no branches for tool calls or memory retrieval; all requests flow straight from the API/CLI into the LLM provider.  Future phases will introduce additional boxes (ToolRunner, MemoryStore, TraceSink) that intercept and enrich this pipeline.