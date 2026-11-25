"""Pydantic request / response models."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Requests ──────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str
    system_prompt: Optional[str] = None

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("message must not be empty or whitespace-only")
        if len(trimmed) > 4000:
            raise ValueError("message must be at most 4000 characters")
        return trimmed


# ── Responses ─────────────────────────────────────────────────────────────────

class ChatMetadata(BaseModel):
    resolution_source: str            # "LIVE_INFERENCE" | "LLM_CACHE"
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: Optional[str] = None
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class MessageOut(BaseModel):
    role: str
    content: str
    metadata: Optional[dict] = None


class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: List[MessageOut]


class HealthResponse(BaseModel):
    status: str
    keys_configured: int
    cache_enabled: bool


class ErrorResponse(BaseModel):
    detail: str
