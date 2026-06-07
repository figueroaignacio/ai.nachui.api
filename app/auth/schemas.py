from pydantic import BaseModel


class AccessTokenResponse(BaseModel):
    """JSON body returned after a successful login or token refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    """Claims decoded from a valid access JWT."""

    sub: str
    jti: str
    exp: int
    type: str = "access"


class RefreshTokenPayload(BaseModel):
    """Claims decoded from a valid refresh JWT."""

    sub: str
    jti: str
    exp: int
    type: str = "refresh"


class GitHubUserInfo(BaseModel):
    """Subset of fields returned by the GitHub /user API."""

    id: int
    login: str
    email: str | None = None
    avatar_url: str | None = None
