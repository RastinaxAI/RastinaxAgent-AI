"""Private FastAPI AI service. V1 legacy raw stream + versioned backend contract."""
import asyncio
import hmac
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.service import AgentError, AgentService, prepare_messages
from app.core.config import get_settings


class ChatRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=3000)
    chat_history: list[dict[str, Any]] | None = None


class ChatResponse(BaseModel):
    request_id: str
    content: str
    provider: str
    model: str


def _http_error(error: AgentError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": "AI request failed"})


async def require_service_auth(authorization: str | None = Header(default=None)):
    config = get_settings()
    if config.environment != "production" and config.allow_anonymous_dev and not config.service_token:
        return
    if not config.service_token:
        raise HTTPException(status_code=503, detail={"code": "SERVICE_AUTH_NOT_CONFIGURED"})
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, config.service_token):
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"},
                            headers={"WWW-Authenticate": "Bearer"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.request_slots = asyncio.Semaphore(get_settings().max_concurrent_requests)
    yield


app = FastAPI(title="Rastinax Marketing AI Agent API", version="2.0.0", lifespan=lifespan)


def get_agent_service() -> AgentService:
    return AgentService(get_settings())


async def _validate_request(request: ChatRequest):
    try:
        prepare_messages(request.user_input, request.chat_history, get_settings())
    except AgentError as exc:
        raise _http_error(exc) from exc


async def _acquire_slot():
    try:
        await asyncio.wait_for(app.state.request_slots.acquire(), timeout=0.1)
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail={"code": "AI_BUSY"}) from exc


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready(response: Response):
    config = get_settings()
    try:
        ready = bool(config.candidates()) and (bool(config.service_token) or (
            config.environment != "production" and config.allow_anonymous_dev
        ))
    except ValueError:
        ready = False
    if not ready:
        response.status_code = 503
    return {"status": "ready" if ready else "not_ready"}


@app.post("/api/v1/chat", dependencies=[Depends(require_service_auth)], deprecated=True)
async def chat_v1(request: ChatRequest):
    """Preserves legacy raw UTF-8 chunks and text/event-stream media type."""
    await _validate_request(request)
    await _acquire_slot()

    async def legacy_chunks():
        try:
            try:
                async for event in get_agent_service().events(request.user_input, request.chat_history):
                    if event["type"] == "delta":
                        yield event["text"]
            except AgentError:
                yield "سرویس هوش مصنوعی موقتاً در دسترس نیست."
        finally:
            app.state.request_slots.release()

    return StreamingResponse(legacy_chunks(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/v2/chat/stream", dependencies=[Depends(require_service_auth)])
async def chat_v2_stream(request: ChatRequest):
    await _validate_request(request)
    await _acquire_slot()
    request_id = uuid.uuid4().hex

    async def chunks():
        try:
            yield _sse("start", {"request_id": request_id})
            try:
                async for event in get_agent_service().events(request.user_input, request.chat_history):
                    if event["type"] == "delta":
                        yield _sse("delta", {"text": event["text"]})
                    elif event["type"] == "done":
                        yield _sse("done", {"provider": event["provider"],
                                            "model": event["model"], "request_id": request_id})
            except AgentError as exc:
                yield _sse("error", {"code": exc.code, "request_id": request_id})
        finally:
            app.state.request_slots.release()

    return StreamingResponse(chunks(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "X-Request-ID": request_id})


@app.post("/api/v2/chat", response_model=ChatResponse, dependencies=[Depends(require_service_auth)])
async def chat_v2(request: ChatRequest):
    await _validate_request(request)
    await _acquire_slot()
    try:
        parts: list[str] = []
        meta: dict[str, str] = {}
        try:
            async for event in get_agent_service().events(request.user_input, request.chat_history):
                if event["type"] == "delta":
                    parts.append(event["text"])
                elif event["type"] == "done":
                    meta = event
        except AgentError as exc:
            raise _http_error(exc) from exc
        if not meta:
            raise _http_error(AgentError("EMPTY_PROVIDER_RESPONSE", 503))
        return ChatResponse(request_id=uuid.uuid4().hex, content="".join(parts),
                            provider=meta["provider"], model=meta["model"])
    finally:
        app.state.request_slots.release()
