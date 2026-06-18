"""
Service layer for the chats module.

Handles:
- Chat CRUD operations (create, list)
- Message persistence
- LangChain / Gemini streaming integration
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator

from google.genai.errors import ServerError

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


def _extract_text_content(content) -> str:
    """Extract string content from LangChain message content (which can be str or list of dicts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            elif hasattr(part, "get"):
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
        return "".join(text_parts)
    return str(content) if content else ""


def _check_needs_tools(messages: list) -> bool:
    """
    Decide if we should bind tools to the LLM.
    We bind tools if:
    1. The conversation already contains tool calls or tool responses (to preserve flow).
    2. The user's last message mentions coding, UI generation, registry, or specific UI component keywords.
    """
    # 1. Check if history has any tool calls or tool messages
    for msg in messages:
        if isinstance(msg, ToolMessage):
            return True
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            return True

    # 2. Check the last user message
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.__class__.__name__ == "HumanMessage" or getattr(msg, "type", None) == "human":
            last_user_msg = msg.content
            break

    if not last_user_msg:
        return False

    # Convert to lowercase for matching
    text = last_user_msg.lower()

    # Keywords indicating UI generation, code, components, registry, etc.
    ui_keywords = [
        "component", "registry", "button", "accordion", "badge", "input",
        "card", "modal", "dialog", "menu", "list", "table", "navbar",
        "create", "build", "generate", "code", "tsx", "react", "ui", "page",
        "crear", "hacer", "generar", "codigo", "código", "pantalla", "diseñar",
        "diseño", "componente", "registro", "documentacion", "docs", "detalles",
        "details", "show", "get", "ver", "registry", "registry_components",
        "tab", "slider", "form", "select", "checkbox", "switch", "avatar"
    ]

    return any(keyword in text for keyword in ui_keywords)


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

    assistant_content_parts: list[str] = []
    max_iterations = 5

    for iteration in range(max_iterations):
        try:
            # Re-evaluate whether tools are needed each iteration.
            # After a tool call, lc_messages will contain ToolMessages so we always re-bind.
            if _check_needs_tools(lc_messages):
                llm_active = llm.bind_tools(tools)
            else:
                llm_active = llm

            response = await llm_active.ainvoke(lc_messages)

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

            # If there are no tool calls left, we already have the full response content from ainvoke!
            # Stream the generated content in chunks to the client to simulate a typewriter effect
            # and avoid a second slow and redundant LLM API request.
            text = _extract_text_content(response.content)
            logger.debug(
                "Response content type=%s, text length=%d for chat %s",
                type(response.content).__name__,
                len(text),
                chat_id,
            )
            if text:
                words = text.split(" ")
                for i, word in enumerate(words):
                    chunk_text = (word + " ") if i < len(words) - 1 else word
                    assistant_content_parts.append(chunk_text)
                    payload = json.dumps({"content": chunk_text, "done": False})
                    yield f"data: {payload}\n\n"
                    await asyncio.sleep(0.005)
            else:
                logger.warning(
                    "Empty response content at iteration %d for chat %s. raw content: %r",
                    iteration,
                    chat_id,
                    response.content,
                )
            break

        except ServerError as exc:
            if exc.status == 503:
                logger.warning(
                    "Gemini 503 (overloaded) at iteration %d for chat %s: %s",
                    iteration,
                    chat_id,
                    exc,
                )
                error_payload = json.dumps(
                    {
                        "content": "The AI model is currently experiencing high demand. Please try again in a moment.",
                        "error": True,
                        "done": True,
                    }
                )
            else:
                logger.exception(
                    "Gemini ServerError at iteration %d for chat %s",
                    iteration,
                    chat_id,
                )
                error_payload = json.dumps(
                    {"content": "Error generating response.", "error": True, "done": True}
                )
            yield f"data: {error_payload}\n\n"
            return
        except Exception:
            logger.exception(
                "Gemini streaming error during iteration %d for chat %s",
                iteration,
                chat_id,
            )
            error_payload = json.dumps(
                {"content": "Error generating response.", "error": True, "done": True}
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
