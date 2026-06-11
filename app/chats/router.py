import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats import service
from app.chats.schemas import ChatRead, MessageCreate, MessageRead
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.users.models import User

router = APIRouter(prefix="/api/chats", tags=["chats"])


@router.post(
    "",
    response_model=ChatRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chat",
)
async def create_chat(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatRead:
    """Create an empty chat session owned by the authenticated user."""
    chat = await service.create_chat(db, current_user.id)
    return ChatRead.model_validate(chat)


@router.get(
    "",
    response_model=list[ChatRead],
    summary="List all chats for the current user",
)
async def list_chats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatRead]:
    """Return all chat sessions for the authenticated user, newest first."""
    chats = await service.list_chats(db, current_user.id)
    return [ChatRead.model_validate(c) for c in chats]


@router.get(
    "/{chat_id}/messages",
    response_model=list[MessageRead],
    summary="Get message history for a chat",
)
async def get_messages(
    chat_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageRead]:
    """Return the message history for *chat_id* in chronological order."""
    chat = await service.get_chat_or_none(db, chat_id, current_user.id)
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
        )

    messages = await service.list_messages(db, chat_id)
    return [MessageRead.model_validate(m) for m in messages]


@router.post(
    "/{chat_id}/messages",
    summary="Send a message and stream the assistant response",
    response_class=StreamingResponse,
)
async def send_message(
    chat_id: uuid.UUID,
    body: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Persist the user message and stream the assistant reply as Server-Sent Events.

    Each SSE chunk is::

        data: {"content": "...", "done": false}\\n\\n

    The final chunk is::

        data: {"content": "", "done": true}\\n\\n
    """
    chat = await service.get_chat_or_none(db, chat_id, current_user.id)
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
        )

    return StreamingResponse(
        service.stream_assistant_response(chat_id, body.content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
