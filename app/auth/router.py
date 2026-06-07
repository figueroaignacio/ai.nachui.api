"""
app/auth/router.py
───────────────────
All authentication endpoints:

  GET  /auth/github            → initiate GitHub OAuth (redirect)
  GET  /auth/github/callback   → OAuth callback handler
  POST /auth/refresh           → rotate refresh token, issue new access token
  POST /auth/logout            → revoke refresh token, clear cookie
  GET  /auth/me                → return current user (kept here for auth context)

Refresh-token cookie:
  Name: refresh_token
  Path: /auth   (covers /auth/refresh and /auth/logout)
  Flags: HttpOnly, Secure, SameSite=Lax
"""

import secrets

import uuid

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer
from jose import ExpiredSignatureError, JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import AccessTokenResponse
from app.auth.service import handle_github_callback
from app.auth.token_service import is_token_valid, revoke_token, store_refresh_token
from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import (
    CredentialsException,
    NoCookieException,
    OAuthCallbackException,
    OAuthStateException,
    TokenExpiredException,
    TokenRevokedException,
)
from app.core.security import (
    REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    set_refresh_cookie,
)
from app.users.models import User
from app.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# ── State cookie helpers ──────────────────────────────────────────────────────

_STATE_COOKIE = "oauth_state"
_signer = URLSafeSerializer(settings.secret_key, salt="oauth-state")


def _create_signed_state() -> str:
    """Generate a random state value and return its HMAC-signed form."""
    raw = secrets.token_urlsafe(32)
    return _signer.dumps(raw)


def _verify_signed_state(signed: str, received: str) -> bool:
    """
    Unsign *signed* (from cookie) and compare the raw value with *received*
    (from the callback query param). Returns False on any tamper or mismatch.
    """
    try:
        raw = _signer.loads(signed)
    except BadSignature:
        return False
    # The callback echoes back the signed value itself (GitHub reflects `state` as-is)
    return secrets.compare_digest(signed, received)


# ── GitHub OAuth initiation ───────────────────────────────────────────────────

@router.get(
    "/github",
    summary="Initiate GitHub OAuth",
    description="Redirects the browser to GitHub's authorization page. "
                "Sets a signed state cookie to prevent CSRF.",
    status_code=302,
)
async def github_login(response: Response) -> RedirectResponse:
    state = _create_signed_state()

    github_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        f"&redirect_uri={settings.github_redirect_uri}"
        f"&scope=read:user,user:email"
        f"&state={state}"
    )

    redirect = RedirectResponse(url=github_url, status_code=302)
    # Store state in a short-lived HttpOnly cookie for CSRF validation
    redirect.set_cookie(
        key=_STATE_COOKIE,
        value=state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=600,  # 10 minutes – OAuth should complete well within this
    )
    return redirect


# ── GitHub OAuth callback ─────────────────────────────────────────────────────

@router.get(
    "/github/callback",
    response_model=AccessTokenResponse,
    summary="GitHub OAuth callback",
    description="Exchanges the authorization code, upserts the user, "
                "issues tokens, and sets the refresh-token cookie.",
)
async def github_callback(
    request: Request,
    response: Response,
    code: str = Query(..., description="Authorization code from GitHub"),
    state: str = Query(..., description="State param echoed back by GitHub"),
    oauth_state: str | None = Cookie(default=None, alias=_STATE_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    # ── CSRF: validate state ──────────────────────────────────────────────────
    if oauth_state is None or not _verify_signed_state(oauth_state, state):
        raise OAuthStateException()

    # Clear the one-time state cookie
    response.delete_cookie(_STATE_COOKIE)

    # ── Delegate to service layer ─────────────────────────────────────────────
    try:
        return await handle_github_callback(code=code, db=db, response=response)
    except ValueError as exc:
        raise OAuthCallbackException(detail=str(exc)) from exc
    except Exception as exc:
        raise OAuthCallbackException(
            detail="Unexpected error during GitHub OAuth callback"
        ) from exc


# ── Token refresh (rotation) ──────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Rotate refresh token",
    description="Reads the refresh token from the HttpOnly cookie, "
                "validates it, revokes the old one, issues a new pair.",
)
async def refresh_tokens(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    if refresh_token is None:
        raise NoCookieException()

    # Decode JWT (signature + expiry)
    try:
        payload = decode_refresh_token(refresh_token)
    except ExpiredSignatureError:
        raise TokenExpiredException()
    except JWTError:
        raise CredentialsException("Invalid refresh token")

    if payload.get("type") != "refresh":
        raise CredentialsException("Token type mismatch")

    jti: str = payload.get("jti", "")
    raw_sub: str = payload.get("sub", "")

    try:
        user_id = uuid.UUID(raw_sub)
    except ValueError:
        raise CredentialsException()

    # DB check: not revoked, not expired
    if not await is_token_valid(db, jti):
        raise TokenRevokedException()

    # Revoke old token (rotation)
    await revoke_token(db, jti)

    # Issue new pair
    new_access, _at_jti, _at_exp = create_access_token(user_id)
    new_refresh, rt_jti, rt_exp = create_refresh_token(user_id)
    await store_refresh_token(db, user_id, rt_jti, rt_exp)
    set_refresh_cookie(response, new_refresh)

    expires_in = settings.access_token_expire_minutes * 60
    return AccessTokenResponse(access_token=new_access, expires_in=expires_in)


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post(
    "/logout",
    status_code=204,
    summary="Logout",
    description="Revokes the refresh token in the DB and clears the cookie.",
)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> None:
    if refresh_token is not None:
        try:
            payload = decode_refresh_token(refresh_token)
            jti = payload.get("jti", "")
            await revoke_token(db, jti)
        except JWTError:
            pass  # invalid token – still clear the cookie

    clear_refresh_cookie(response)


# ── Current user (auth-scoped convenience endpoint) ───────────────────────────

@router.get(
    "/me",
    response_model=UserRead,
    summary="Get authenticated user",
    description="Returns the profile of the currently authenticated user. "
                "Requires a valid Bearer access token in the Authorization header.",
)
async def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)
