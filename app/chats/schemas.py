import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.chats.models import MessageRole


class ChatCreate(BaseModel):
    """Request body for creating a new chat (no fields required — server sets all)."""

    model_config = ConfigDict(strict=True)


class ChatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    """Request body for sending a message to a chat."""

    model_config = ConfigDict(strict=True)

    content: str = Field(..., min_length=1, max_length=32_000)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chat_id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
