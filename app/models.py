"""Request/response schemas for the HTTP API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    conversation_id: int | None = None


class ConversationCreate(BaseModel):
    title: str = Field("New chat", min_length=1, max_length=200)


class ConversationRename(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class StructuredRequest(BaseModel):
    """Request for the schema-validated endpoint."""
    prompt: str = Field(..., min_length=1, max_length=8000)


class BenchmarkRequest(BaseModel):
    """Request for the in-process benchmark endpoint."""
    prompt: str = Field(
        "Explain what an operating system kernel does in three short sentences.",
        min_length=1,
        max_length=2000,
    )
    runs: int = Field(3, ge=1, le=20)
    warmup: bool = True
