import os
    import time
    from typing import List, Optional, Any, Dict

from fastapi import FastAPI, HTTPException, APIRouter
from pydantic import BaseModel

    from core.runtime import BillyRuntime

# Adapter imports for optional Agent Zero integration.  These are only
# used when the feature flag ENABLE_AGENT_ZERO_INTEGRATION is set.  They
# allow Billy to delegate tool execution and memory storage to Agent Zero
# while keeping Billy as the orchestrator.
from adapter_impl.agentzero_adapter import (
    AgentZeroToolRegistryAdapter,
    AgentZeroMemoryAdapter,
    AgentZeroTraceAdapter,
)
from adapter_impl.tool_runner import LocalToolRunner

    # ----------------------------
    # Optional Mongo (authoritative DB)
    # ----------------------------
    _mongo_db = None
    _mongo_enabled = False

    try:
        from pymongo import MongoClient  # type: ignore
        from datetime import datetime, timezone

        def _load_env_minimal(env_path: str = ".env") -> None:
            if not os.path.exists(env_path):
                return
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if (not line) or line.startswith("#") or ("=" not in line):
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

        _load_env_minimal(".env")

        if os.getenv("BILLY_DB_ENGINE", "").lower() == "mongo":
            _mongo_enabled = True
            uri = os.environ.get("BILLY_MONGO_URI", "mongodb://127.0.0.1:27017")
            dbn = os.environ.get("BILLY_MONGO_DB", "billy")
            client = MongoClient(uri, serverSelectionTimeoutMS=2000)
            _mongo_db = client[dbn]
    except Exception:
        # keep server running even if mongo is misconfigured
        _mongo_db = None
        _mongo_enabled = False

    app = FastAPI(title="Billy v2 API", version="2.2")

    # Default to repo root; allow override via env var
    ROOT_PATH = os.getenv("BILLY_V2_ROOT", os.path.abspath(os.path.dirname(__file__)))
    runtime = BillyRuntime(root_path=ROOT_PATH)

# -----------------------------------------------------------------------------
# Optional Agent Zero integration
#
# Set the environment variable ``ENABLE_AGENT_ZERO_INTEGRATION`` to ``true`` to
# enable additional endpoints that expose Agent Zero tools and memory
# functionality.  When disabled (the default), Billy operates using its
# built‑in runtime and Mongo memory endpoints only.  This feature flag
# preserves backward compatibility and ensures that Agent Zero remains a helper
# rather than replacing Billy.
#
# The ``AGENT_ZERO_ROOT`` environment variable may be used to specify the
# location of the Agent Zero repository on disk.  If not provided, it
# defaults to a directory named ``agent-zero-main`` inside the Billy root.
ENABLE_AGENT_ZERO_INTEGRATION = os.getenv("ENABLE_AGENT_ZERO_INTEGRATION", "false").lower() == "true"
if ENABLE_AGENT_ZERO_INTEGRATION:
    A0_ROOT = os.getenv("AGENT_ZERO_ROOT", os.path.join(ROOT_PATH, "agent-zero-main"))
    # Initialise adapters
    tool_registry = AgentZeroToolRegistryAdapter(A0_ROOT)
    memory_adapter = AgentZeroMemoryAdapter(A0_ROOT)
    trace_adapter = AgentZeroTraceAdapter()
    tool_runner = LocalToolRunner(tool_registry, trace_adapter)

    # Define request model for tool runs
    class A0ToolRunRequest(BaseModel):
        args: Dict[str, Any]
        use_docker: Optional[bool] = False

    # Create a router to group integration endpoints
    integration_router = APIRouter()

    @integration_router.get("/v1/a0/tools")
    async def list_a0_tools():
        """Return a list of available Agent Zero tool specs."""
        specs = await tool_registry.list_tools()
        return {
            "tools": [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "args_schema": spec.args_schema,
                }
                for spec in specs
            ]
        }

    @integration_router.get("/v1/a0/tool/{name}")
    async def get_a0_tool(name: str):
        """Return the schema for a specific Agent Zero tool."""
        spec = await tool_registry.get_schema(name)
        if spec is None:
            raise HTTPException(status_code=404, detail="Tool not found")
        return {
            "name": spec.name,
            "description": spec.description,
            "args_schema": spec.args_schema,
        }

    @integration_router.post("/v1/a0/tool/{name}/run")
    async def run_a0_tool(name: str, req: A0ToolRunRequest):
        """Execute an Agent Zero tool and return its result."""
        try:
            result = await tool_runner.execute(name, req.args, use_docker=req.use_docker or False)
            return {"result": result}
        except Exception as exc:
            # Surface tool errors as HTTP 500; caller must interpret message
            raise HTTPException(status_code=500, detail=str(exc))

    @integration_router.post("/v1/a0/memory/put")
    async def a0_memory_put(req: MemoryPutRequest):
        """Write a key/value pair to Agent Zero memory."""
        await memory_adapter.write(req.key, req.value, tags=req.tags or [])
        return {"ok": True, "key": req.key}

    @integration_router.get("/v1/a0/memory/get")
    async def a0_memory_get(key: str):
        """Retrieve a value from Agent Zero memory."""
        results = await memory_adapter.query(key)
        if not results:
            return {"ok": True, "found": False, "key": key, "value": None}
        return {
            "ok": True,
            "found": True,
            "key": results[0]["key"],
            "value": results[0]["value"],
        }

    # Mount the integration router under the main app.  Paths are defined above.
    app.include_router(integration_router)

    # ----------------------------
    # Existing simple endpoints
    # ----------------------------
    class AskRequest(BaseModel):
        prompt: str

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "root_path": ROOT_PATH,
            "mongo_enabled": bool(_mongo_enabled),
            "mongo_connected": (_mongo_db is not None),
        }

    @app.post("/ask")
    def ask(req: AskRequest):
        answer = runtime.ask(req.prompt)
        return {"answer": answer}

    # ----------------------------
    # OpenAI-compatible endpoints (minimal)
    # ----------------------------
    class ChatMessage(BaseModel):
        role: str
        content: str

    class ChatCompletionRequest(BaseModel):
        model: Optional[str] = "billy-v2"
        messages: List[ChatMessage]
        temperature: Optional[float] = None
        max_tokens: Optional[int] = None
        stream: Optional[bool] = False

    @app.get("/v1/models")
    def v1_models():
        return {"object": "list", "data": [{"id": "billy-v2", "object": "model", "owned_by": "bitscon"}]}

    @app.post("/v1/chat/completions")
    def v1_chat_completions(req: ChatCompletionRequest):
        # simple: last user message becomes prompt
        prompt = ""
        for m in req.messages:
            if m.role == "user":
                prompt = m.content
        if not prompt:
            prompt = req.messages[-1].content if req.messages else ""

        answer = runtime.ask(prompt)
        return {
            "id": "chatcmpl-billyv2",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model or "billy-v2",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # ----------------------------
    # Memory endpoints (Mongo-backed)
    # ----------------------------
    class MemoryPutRequest(BaseModel):
        key: str
        value: Any
        tags: Optional[List[str]] = None

    @app.post("/v1/memory/put")
    def memory_put(req: MemoryPutRequest):
        if _mongo_db is None:
            raise HTTPException(status_code=503, detail="Mongo not configured/connected")

        doc = {
            "key": req.key,
            "value": req.value,
            "tags": req.tags or [],
            "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }

        _mongo_db["memory"].update_one({"key": req.key}, {"$set": doc}, upsert=True)
        return {"ok": True, "key": req.key}

    @app.get("/v1/memory/get")
    def memory_get(key: str):
        if _mongo_db is None:
            raise HTTPException(status_code=503, detail="Mongo not configured/connected")

        doc = _mongo_db["memory"].find_one({"key": key}, {"_id": 0})
        if not doc:
            return {"ok": True, "found": False, "key": key, "value": None}

        return {"ok": True, "found": True, **doc}