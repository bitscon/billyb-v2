import os
import time
from typing import List, Optional, Any, Dict

from fastapi import FastAPI, HTTPException, APIRouter
from pydantic import BaseModel

from v2.core.runtime import BillyRuntime

# Optional Agent Zero adapters
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
                if not line or line.startswith("#") or "=" not in line:
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
    _mongo_db = None
    _mongo_enabled = False


# ----------------------------
# App + Runtime
# ----------------------------
app = FastAPI(title="Billy v2 API", version="2.2")

ROOT_PATH = os.getenv(
    "BILLY_V2_ROOT",
    os.path.abspath(os.path.dirname(__file__)),
)

runtime = BillyRuntime(config=None)

# -----------------------------------------------------------------------------
# Optional Agent Zero integration
# -----------------------------------------------------------------------------
ENABLE_AGENT_ZERO_INTEGRATION = (
    os.getenv("ENABLE_AGENT_ZERO_INTEGRATION", "false").lower() == "true"
)

if ENABLE_AGENT_ZERO_INTEGRATION:
    A0_ROOT = os.getenv("AGENT_ZERO_ROOT", os.path.join(ROOT_PATH, "agent-zero-main"))

    tool_registry = AgentZeroToolRegistryAdapter(A0_ROOT)
    memory_adapter = AgentZeroMemoryAdapter(A0_ROOT)
    trace_adapter = AgentZeroTraceAdapter()
    tool_runner = LocalToolRunner(tool_registry, trace_adapter)

    integration_router = APIRouter()

    class A0ToolRunRequest(BaseModel):
        args: Dict[str, Any]
        use_docker: Optional[bool] = False

    @integration_router.get("/v1/a0/tools")
    async def list_a0_tools():
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
        try:
            result = await tool_runner.execute(
                name,
                req.args,
                use_docker=req.use_docker or False,
            )
            return {"result": result}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    app.include_router(integration_router)


# ----------------------------
# Health + Ask
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
    result = runtime.run_turn(
        user_input=req.prompt,
        session_context={},
    )
    return result


# ----------------------------
# OpenAI-compatible endpoints
# ----------------------------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = "billy-v2"
    messages: List[ChatMessage]


class CompletionRequest(BaseModel):
    model: Optional[str] = "billy-v2"
    prompt: str


@app.get("/v1/models")
def v1_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "billy-v2",
                "object": "model",
                "owned_by": "bitscon",
            }
        ],
    }


@app.post("/v1/chat/completions")
def v1_chat_completions(req: ChatCompletionRequest):
    prompt = next(
        (m.content for m in reversed(req.messages) if m.role == "user"),
        "",
    )

    answer = runtime.ask(prompt)

    return {
        "id": "chatcmpl-billyv2",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or "billy-v2",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": answer,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


@app.post("/v1/completions")
def v1_completions(req: CompletionRequest):
    result = runtime.run_turn(
        user_input=req.prompt,
        session_context={},
    )

    text: str = ""
    if isinstance(result, dict):
        final_output = result.get("final_output")
        if isinstance(final_output, dict):
            message = final_output.get("message")
            if isinstance(message, str):
                text = message
            else:
                text = str(final_output)
        elif final_output is None:
            text = ""
        else:
            text = str(final_output)
    else:
        text = str(result)

    return {
        "id": "billy-v1",
        "object": "text_completion",
        "choices": [
            {
                "index": 0,
                "text": text,
                "finish_reason": "stop",
            }
        ],
    }
