"""StackChan text chat with a self-hosted OpenAI-compatible model."""
import json
import os
from typing import Annotated, Literal
from urllib.parse import urlsplit

import anyio
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .auth import current_user

router = APIRouter(prefix="/api/v1/companion", tags=["companion"])
_capacity = anyio.CapacityLimiter(2)
_message_text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]
_system_prompt = """你是时宜 App 里的 StackChan，亲切但不撒娇过头，跟随用户的语言简短回答。
你可以陪用户聊天、听他们说，或在用户愿意时提议休息、散步、做个短呼吸练习。
你没有手环、日程或当前节气的数据。聊节气时把民俗当作文化，不作为健康建议。
不要诊断、开药或声称已替用户执行操作。若用户描述紧急危险，优先建议立即寻求现实援助。
仅返回 JSON：{"reply":"回复正文","reaction":"nod"}。
reaction 只能是 nod（回应）、cheer（庆祝）、calm（安静陪伴）之一。"""


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: _message_text


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=9)

    @model_validator(mode="after")
    def validate_turns(self):
        if len(self.messages) % 2 == 0 or any(
            message.role != ("assistant" if index % 2 else "user")
            for index, message in enumerate(self.messages)
        ):
            raise ValueError("Send complete alternating turns followed by a user message")
        return self


class ChatReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: _message_text
    reaction: Literal["nod", "cheer", "calm"]


def _model_config() -> tuple[str, str]:
    model = os.environ.get("SHIYI_COMPANION_MODEL", "").strip()
    address = os.environ.get(
        "SHIYI_COMPANION_MODEL_URL", "http://127.0.0.1:11434/v1/chat/completions"
    )
    try:
        url = urlsplit(address)
        if (
            not model or len(model) > 128
            or url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1")
            or url.username is not None or url.password is not None or not url.port
            or url.path != "/v1/chat/completions" or url.query or url.fragment
        ):
            raise ValueError
    except ValueError:
        raise HTTPException(503, "Companion model is not configured") from None
    return address, model


async def _complete_chat(payload: ChatRequest, address: str, model: str) -> ChatReply:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt},
            *(message.model_dump() for message in payload.messages),
        ],
        "temperature": 0.6,
        "stream": False,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }
    async with (
        httpx.AsyncClient(timeout=25, trust_env=False, follow_redirects=False) as client,
        client.stream("POST", address, json=body) as response,
    ):
        response.raise_for_status()
        content = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            content.extend(chunk)
            if len(content) > 65536:
                raise ValueError("Model response exceeds size limit")
    result = json.loads(content)
    return ChatReply.model_validate_json(result["choices"][0]["message"]["content"])


@router.post(
    "/chat",
    response_model=ChatReply,
    responses={401: {"description": "Authentication required"},
               429: {"description": "Model busy"}, 502: {"description": "Model request failed"},
               503: {"description": "Model disabled"}, 504: {"description": "Model timed out"}},
)
async def chat(payload: ChatRequest, _user: Annotated[str, Depends(current_user)]) -> ChatReply:
    address, model = _model_config()
    try:
        _capacity.acquire_nowait()
    except anyio.WouldBlock:
        raise HTTPException(429, "Companion is busy", headers={"Retry-After": "2"}) from None
    try:
        with anyio.fail_after(35):
            return await _complete_chat(payload, address, model)
    except (TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "Companion model timed out") from None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
        raise HTTPException(502, "Companion model returned an unavailable reply") from None
    finally:
        _capacity.release()
