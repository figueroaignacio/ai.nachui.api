import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import User


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Return a User by primary key, or None."""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_github_id(db: AsyncSession, github_id: str) -> User | None:
    """Return a User by their GitHub numeric ID (stored as string), or None."""
    result = await db.execute(select(User).where(User.github_id == github_id))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Return a User by email address, or None."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_or_create_user(
    db: AsyncSession,
    github_id: str,
    github_username: str,
    email: str | None,
    avatar_url: str | None,
) -> User:
    """
    Upsert a user from GitHub OAuth profile data.

    Lookup order:
      1. github_id  (primary)
      2. email      (fallback – links an existing account)

    On match: refreshes mutable profile fields (username, avatar, email).
    On miss:  inserts a new User row (flush, no commit – caller owns the tx).
    """
    user = await get_user_by_github_id(db, github_id)

    if user is None and email:
        user = await get_user_by_email(db, email)
        if user is not None:
            user.github_id = github_id

    if user is None:
        user = User(
            github_id=github_id,
            github_username=github_username,
            email=email,
            avatar_url=avatar_url,
        )
        db.add(user)
        await db.flush()
    else:
        user.github_username = github_username
        user.avatar_url = avatar_url
        if email:
            user.email = email

    return user
