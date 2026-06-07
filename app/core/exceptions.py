"""
app/core/exceptions.py
───────────────────────
Domain-level HTTPException subclasses shared across all feature modules.
"""

from fastapi import HTTPException, status


class CredentialsException(HTTPException):
    """401 – token is missing, malformed, or the user does not exist."""

    def __init__(self, detail: str = "Could not validate credentials") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class TokenExpiredException(HTTPException):
    """401 – JWT access token has expired."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )


class TokenRevokedException(HTTPException):
    """401 – Refresh token has been revoked (logged out or rotated)."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )


class NoCookieException(HTTPException):
    """401 – Refresh token cookie is absent."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cookie missing",
        )


class OAuthStateException(HTTPException):
    """400 – OAuth state param is missing or does not match the signed cookie."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or missing OAuth state parameter (possible CSRF)",
        )


class OAuthCallbackException(HTTPException):
    """400 – GitHub OAuth callback failed (bad code, network error, etc.)."""

    def __init__(self, detail: str = "OAuth callback failed") -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


class UserNotFoundException(HTTPException):
    """404 – Requested user does not exist."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
