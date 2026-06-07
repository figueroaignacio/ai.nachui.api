"""
app/core/dependencies.py
─────────────────────────
Shared FastAPI dependencies injected into routes across feature modules.
"""

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import CredentialsException, TokenExpiredException
from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate a Bearer access token from the Authorization header.

    Returns the authenticated User ORM instance.
    Raises 401 if the token is missing, expired, or invalid.

    Import-cycle note: we import users.service lazily inside the function
    so that users/ does not depend on core/ at import time while core/
    depends on users/.
    """
    from app.users.service import get_user_by_id  # deferred to avoid circular import

    if credentials is None:
        raise CredentialsException("Authorization header missing")

    token = credentials.credentials

    try:
        payload = decode_access_token(token)
    except ExpiredSignatureError:
        raise TokenExpiredException()
    except JWTError:
        raise CredentialsException()

    if payload.get("type") != "access":
        raise CredentialsException("Invalid token type")

    raw_sub: str | None = payload.get("sub")
    if not raw_sub:
        raise CredentialsException()

    try:
        user_id = uuid.UUID(raw_sub)
    except ValueError:
        raise CredentialsException()

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise CredentialsException("User not found")

    return user
