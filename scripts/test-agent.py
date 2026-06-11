import asyncio
import sys
import os
import json
from sqlalchemy import select

# Add parent directory to path so app can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.main  # Ensure all models are loaded
from app.core.database import AsyncSessionLocal
from app.chats.models import Chat, Message
from app.users.models import User
from app.chats.service import stream_assistant_response, create_chat

async def test_agent():
    prompt = "Create a user profile card using the badge component from the registry to display their role."
    print(f"Testing agent with prompt:\n' {prompt} '\n")
    print("Connecting to database...")

    async with AsyncSessionLocal() as db:
        # 1. Ensure we have a user
        result = await db.execute(select(User))
        user = result.scalars().first()
        created_user = False
        if not user:
            print("No users found. Creating a test user...")
            user = User(
                email="test_agent@example.com",
                github_id=12345,
                github_login="test_agent",
                avatar_url="https://example.com/avatar.png",
                is_active=True
            )
            db.add(user)
            await db.flush()
            created_user = True

        # 2. Create a test chat
        print("Creating a new test chat...")
        chat = await create_chat(db, user.id)
        await db.commit()
        chat_id = chat.id
        print(f"Chat created successfully with ID: {chat_id}")

    # 3. Stream response
    print("\nStreaming response from NachAI (including tool calls)...")
    print("-" * 80)
    
    try:
        async for chunk in stream_assistant_response(chat_id, prompt):
            # Parse SSE data
            if chunk.startswith("data: "):
                data_str = chunk[6:].strip()
                if not data_str:
                    continue
                data = json.loads(data_str)
                content = data.get("content", "")
                done = data.get("done", False)
                if content:
                    # Print in real-time
                    sys.stdout.write(content)
                    sys.stdout.flush()
                if done:
                    break
    except Exception as e:
        print(f"\nError streaming: {e}")
    
    print("\n" + "-" * 80)

    # 4. Clean up test data
    print("\nCleaning up test data...")
    async with AsyncSessionLocal() as db:
        # Load chat and messages to delete
        result = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat_to_delete = result.scalar_one_or_none()
        if chat_to_delete:
            await db.delete(chat_to_delete)
        
        if created_user:
            result = await db.execute(select(User).where(User.id == user.id))
            user_to_delete = result.scalar_one_or_none()
            if user_to_delete:
                await db.delete(user_to_delete)
                
        await db.commit()
    print("Cleanup complete!")

if __name__ == "__main__":
    asyncio.run(test_agent())
