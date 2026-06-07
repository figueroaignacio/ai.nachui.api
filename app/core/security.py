"""
app/core/security.py
─────────────────────
JWT creation / decoding (RS256) and HttpOnly cookie helpers.
Never imports from feature modules – only from core.config.
"""

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from starlette.responses import Response

from app.core.config import get_settings

settings = get_settings()

# ── Constants ─────────────────────────────────────────────────────────────────

ALGORITHM = settings.jwt_algorithm  # "RS256"
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"  # covers /auth/refresh and /auth/logout


# ── Access token ──────────────────────────────────────────────────────────────

def create_access_token(user_id: uuid.UUID) -> tuple[str, str, datetime]:
    """
    Create a short-lived RS256 access JWT.

    Returns:
        (encoded_token, jti, expires_at)
    """
    jti = str(uuid.uuid4())
    expires_at = datetime.now(tz=timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "exp": expires_at,
        "type": "access",
    }
    token = jwt.encode(payload, settings.rsa_private_key, algorithm=ALGORITHM)
    return token, jti, expires_at


def decode_access_token(token: str) -> dict:
    """
    Decode and validate an access JWT using the RSA public key.

    Raises:
        jose.JWTError – on any validation failure.
        jose.ExpiredSignatureError – subclass of JWTError, token is expired.
    """
    return jwt.decode(token, settings.rsa_public_key, algorithms=[ALGORITHM])


# ── Refresh token ─────────────────────────────────────────────────────────────

def create_refresh_token(user_id: uuid.UUID) -> tuple[str, str, datetime]:
    """
    Create a long-lived RS256 refresh JWT.

    Returns:
        (encoded_token, jti, expires_at)
    """
    jti = str(uuid.uuid4())
    expires_at = datetime.now(tz=timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "exp": expires_at,
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.rsa_private_key, algorithm=ALGORITHM)
    return token, jti, expires_at


def decode_refresh_token(token: str) -> dict:
    """
    Decode and validate a refresh JWT using the RSA public key.

    Raises:
        jose.JWTError – on any validation failure.
    """
    return jwt.decode(token, settings.rsa_public_key, algorithms=[ALGORITHM])


# ── Cookie helpers ────────────────────────────────────────────────────────────

def set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the refresh token as an HttpOnly, Secure, SameSite=Lax cookie."""
    max_age = settings.refresh_token_expire_days * 24 * 60 * 60
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=REFRESH_COOKIE_PATH,
        max_age=max_age,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Expire the refresh token cookie (Max-Age=0)."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )
