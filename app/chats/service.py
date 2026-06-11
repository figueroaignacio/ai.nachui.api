"""
Service layer for the chats module.

Handles:
- Chat CRUD operations (create, list)
- Message persistence
- LangChain / Gemini streaming integration
"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chats.models import Chat, Message, MessageRole
from app.core.database import AsyncSessionLocal
from app.rag.llm import get_llm
from app.rag.prompts import _SYSTEM_PROMPT
from app.rag.tools import async_execute_tool, tools

logger = logging.getLogger(__name__)


async def create_chat(db: AsyncSession, user_id: uuid.UUID) -> Chat:
    """Create a new empty chat owned by *user_id*."""
    chat = Chat(user_id=user_id)
    db.add(chat)
    await db.flush()
    await db.refresh(chat)
    return chat


async def list_chats(db: AsyncSession, user_id: uuid.UUID) -> list[Chat]:
    """Return all chats for *user_id*, most-recent first."""
    result = await db.execute(
        select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_chat_or_none(
    db: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID
) -> Chat | None:
    """Fetch a chat that belongs to *user_id*, or return None."""
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_messages(db: AsyncSession, chat_id: uuid.UUID) -> list[Message]:
    """Return all messages for *chat_id*, oldest first."""
    result = await db.execute(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def save_message(
    db: AsyncSession,
    chat_id: uuid.UUID,
    role: MessageRole,
    content: str,
) -> Message:
    """Persist a single message and return the ORM instance."""
    message = Message(chat_id=chat_id, role=role, content=content)
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def _update_chat_title(db: AsyncSession, chat: Chat, first_message: str) -> None:
    """Set the chat title to the first ~60 chars of the user's first message."""
    if chat.title is None:
        chat.title = first_message[:60].rstrip()
        await db.flush()


def _build_lc_messages(
    history: list[Message], new_content: str
) -> list[SystemMessage | HumanMessage | AIMessage]:
    """Convert stored messages + the new user message into LangChain message objects."""
    lc_messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=_SYSTEM_PROMPT)
    ]
    for msg in history:
        if msg.role == MessageRole.user:
            lc_messages.append(HumanMessage(content=msg.content))
        else:
            lc_messages.append(AIMessage(content=msg.content))
    lc_messages.append(HumanMessage(content=new_content))
    return lc_messages


async def stream_assistant_response(
    chat_id: uuid.UUID,
    user_content: str,
) -> AsyncGenerator[str, None]:
    """
    Core streaming coroutine consumed by the route.

    Workflow:
    1. Load conversation history before adding the new message.
    2. Save the user message & update title if first message, then commit.
    3. Stream chunks from Gemini via ChatGoogleGenerativeAI (no DB session held).
    4. Persist the completed assistant message, then commit.
    5. Yield SSE-formatted chunks throughout.
    """
    async with AsyncSessionLocal() as db:
        # 1. Fetch chat to ensure it exists and load for _update_chat_title
        result = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()
        if chat is None:
            logger.error("Chat %s not found for streaming", chat_id)
            return

        # 2. Load prior conversation history (before saving new message)
        history_result = await db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at)
        )
        prior_history = list(history_result.scalars().all())

        # 3. Save the user message & update title
        await save_message(db, chat_id, MessageRole.user, user_content)
        await _update_chat_title(db, chat, user_content)
        await db.commit()

    lc_messages = _build_lc_messages(prior_history, user_content)

    # 4. Run tool execution agent loop
    llm = get_llm()
    llm_with_tools = llm.bind_tools(tools)

    assistant_content_parts: list[str] = []
    max_iterations = 5

    for iteration in range(max_iterations):
        try:
            response = await llm_with_tools.ainvoke(lc_messages)

            # If the model requests a tool call, run it and append responses to conversation history
            if response.tool_calls:
                lc_messages.append(response)
                for tool_call in response.tool_calls:
                    t_name = tool_call["name"]
                    t_args = tool_call["args"]
                    t_id = tool_call["id"]

                    # Send a progress indicator chunk to frontend
                    status_msg = f"\n*[Calling tool '{t_name}' with args {json.dumps(t_args)}...]*\n"
                    yield f"data: {json.dumps({'content': status_msg, 'done': False})}\n\n"

                    # Execute tool
                    tool_output = await async_execute_tool(t_name, t_args)

                    # Append ToolMessage
                    lc_messages.append(
                        ToolMessage(content=tool_output, tool_call_id=t_id)
                    )
                continue

            # If there are no tool calls left, stream the final response to the user
            async for chunk in llm.astream(lc_messages):
                text = chunk.content if isinstance(chunk.content, str) else ""
                if text:
                    assistant_content_parts.append(text)
                    payload = json.dumps({"content": text, "done": False})
                    yield f"data: {payload}\n\n"
            break

        except Exception:
            logger.exception(
                "Gemini streaming error during iteration %d for chat %s",
                iteration,
                chat_id,
            )
            error_payload = json.dumps(
                {"content": "Error generating response.", "done": True}
            )
            yield f"data: {error_payload}\n\n"
            return

    # 5. Persist the full assistant message
    full_response = "".join(assistant_content_parts)
    if full_response:
        async with AsyncSessionLocal() as db:
            await save_message(db, chat_id, MessageRole.assistant, full_response)
            await db.commit()

    # 6. Final "done" sentinel
    yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"
