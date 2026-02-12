from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import time
import uuid

router = APIRouter(prefix="/v1")

@router.get("/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "billy-v2",
                "object": "model",
                "owned_by": "bitscon"
            }
        ]
    }

@router.post("/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()

    messages = body.get("messages", [])
    prompt = messages[-1]["content"] if messages else ""

    # 🔁 TEMP RESPONSE (replace later with Billy's real logic)
    reply = f"Billy v2 online. You said: {prompt}"

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "billy-v2",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": reply
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }
