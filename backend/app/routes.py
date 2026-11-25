"""FastAPI route handlers."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app import db
from app.config import settings
from app.llm import complete
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ChatMetadata,
    HealthResponse,
    MessageOut,
    SessionMessagesResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    db_ok = await db.check_db()
    keys_ok = len(settings.LLM_API_KEYS) > 0
    if not db_ok or not keys_ok:
        return JSONResponse(status_code=503, content={"detail": "service unhealthy"})
    return HealthResponse(
        status="ok",
        keys_configured=len(settings.LLM_API_KEYS),
        cache_enabled=True,
    )


# ── Chat ──────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    x_simulate_failure: Optional[str] = Header(None),
) -> ChatResponse:
    session_id = body.session_id
    user_message = body.message  # already trimmed by validator

    # Determine system prompt
    system_prompt_to_use = settings.DEFAULT_SYSTEM_PROMPT
    incoming_prompt = body.system_prompt

    # Check if session already has a stored prompt
    stored_prompt = await db.get_session_prompt(session_id)
    if incoming_prompt is not None:
        system_prompt_to_use = incoming_prompt
    elif stored_prompt is not None:
        system_prompt_to_use = stored_prompt

    # Build message list: system + history + new user message
    messages = [{"role": "system", "content": system_prompt_to_use}]
    history = await db.get_session_messages(session_id)
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_message})

    # LLM call with failover
    sim_header = x_simulate_failure if settings.ENABLE_FAILURE_SIMULATION else None

    from litellm.exceptions import ServiceUnavailableError
    try:
        reply, metadata = await complete(messages, sim_header=sim_header)
    except ServiceUnavailableError:
        return JSONResponse(status_code=503, content={"detail": "all providers unavailable"})

    # Persist (only on success)
    await db.save_turn(
        session_id=session_id,
        user_content=user_message,
        assistant_content=reply,
        metadata=metadata,
        system_prompt=incoming_prompt,
    )

    return ChatResponse(
        session_id=session_id,
        reply=reply,
        metadata=ChatMetadata(**metadata),
    )


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def session_messages(session_id: str) -> SessionMessagesResponse:
    exists = await db.session_exists(session_id)
    if not exists:
        return JSONResponse(status_code=404, content={"detail": "session not found"})

    rows = await db.get_session_messages(session_id)
    out = []
    for r in rows:
        m = MessageOut(role=r["role"], content=r["content"])
        if r.get("metadata"):
            # Only include the three fields specified + any extras
            m.metadata = r["metadata"]
        out.append(m)
    return SessionMessagesResponse(session_id=session_id, messages=out)
