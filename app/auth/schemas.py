"""
app/auth/schemas.py
────────────────────
Pydantic v2 schemas scoped to the auth feature module.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class AccessTokenResponse(BaseModel):
    """JSON body returned after a successful login or token refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires


class TokenPayload(BaseModel):
    """Claims decoded from a valid access JWT."""

    sub: str   # str(user_id UUID)
    jti: str
    exp: int
    type: str = "access"


class RefreshTokenPayload(BaseModel):
    """Claims decoded from a valid refresh JWT."""

    sub: str   # str(user_id UUID)
    jti: str
    exp: int
    type: str = "refresh"


class GitHubUserInfo(BaseModel):
    """Subset of fields returned by the GitHub /user API."""

    id: int             # GitHub's numeric user id
    login: str          # GitHub username / handle
    email: str | None = None
    avatar_url: str | None = None
