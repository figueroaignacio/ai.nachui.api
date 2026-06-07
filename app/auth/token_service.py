import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken


async def store_refresh_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    jti: str,
    expires_at: datetime,
) -> RefreshToken:
    """
    Persist a new refresh token record linked to *user_id*.
    Flushes without committing – caller owns the transaction.
    """
    token = RefreshToken(
        user_id=user_id,
        jti=jti,
        expires_at=expires_at,
        revoked=False,
    )
    db.add(token)
    await db.flush()
    return token


async def get_token_by_jti(db: AsyncSession, jti: str) -> RefreshToken | None:
    """Return the RefreshToken row matching *jti*, or None."""
    result = await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))
    return result.scalar_one_or_none()


async def is_token_valid(db: AsyncSession, jti: str) -> bool:
    """
    Return True iff:
      - the jti exists in the DB
      - it has not been revoked
      - it has not expired (wall-clock check, in addition to JWT signature check)
    """
    token = await get_token_by_jti(db, jti)
    if token is None or token.revoked:
        return False
    now = datetime.now(tz=timezone.utc)
    expires = token.expires_at

    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now


async def revoke_token(db: AsyncSession, jti: str) -> bool:
    """
    Mark the token with *jti* as revoked.
    Returns True if found and revoked, False if not found.
    """
    token = await get_token_by_jti(db, jti)
    if token is None:
        return False
    token.revoked = True
    await db.flush()
    return True


async def revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """
    Revoke every non-revoked refresh token for *user_id*.
    Useful for "log out all devices" flows.
    """
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
        )
    )
    for token in result.scalars().all():
        token.revoked = True
    await db.flush()
