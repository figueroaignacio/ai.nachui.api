"""
app/auth/service.py
────────────────────
Orchestration layer for the GitHub OAuth flow and token issuance.
Calls out to:
  - GitHub's OAuth token and user APIs (via httpx)
  - users.service  – get_or_create_user
  - auth.token_service – store_refresh_token
  - core.security  – create_access_token / create_refresh_token / set_refresh_cookie
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.auth.schemas import AccessTokenResponse, GitHubUserInfo
from app.auth.token_service import store_refresh_token
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    set_refresh_cookie,
)
from app.users.service import get_or_create_user

settings = get_settings()

# ── GitHub API constants ──────────────────────────────────────────────────────

_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
_GITHUB_EMAILS_URL = "https://api.github.com/user/emails"
_REQUEST_TIMEOUT = 10  # seconds


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _exchange_code(code: str) -> str:
    """
    POST to GitHub's token endpoint and return the raw access token string.

    Raises:
        httpx.HTTPStatusError – non-2xx response from GitHub.
        ValueError – GitHub returned an error in the JSON body.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_redirect_uri,
            },
            timeout=_REQUEST_TIMEOUT,
        )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ValueError(
            f"GitHub OAuth error: {data.get('error_description', data['error'])}"
        )
    return data["access_token"]


async def _fetch_github_user(github_token: str) -> GitHubUserInfo:
    """
    GET /user (and optionally /user/emails for private emails).
    Returns a GitHubUserInfo with the primary verified email, if available.
    """
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            _GITHUB_USER_URL, headers=headers, timeout=_REQUEST_TIMEOUT
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()

        email: str | None = user_data.get("email")

        # If the primary email is private, fetch from the emails endpoint
        if not email:
            emails_resp = await client.get(
                _GITHUB_EMAILS_URL, headers=headers, timeout=_REQUEST_TIMEOUT
            )
            if emails_resp.status_code == 200:
                for entry in emails_resp.json():
                    if entry.get("primary") and entry.get("verified"):
                        email = entry["email"]
                        break

    return GitHubUserInfo(
        id=user_data["id"],
        login=user_data["login"],
        email=email,
        avatar_url=user_data.get("avatar_url"),
    )


# ── Public API ────────────────────────────────────────────────────────────────

async def handle_github_callback(
    code: str,
    db: AsyncSession,
    response: Response,
) -> AccessTokenResponse:
    """
    Full OAuth callback orchestration:

      1. Exchange the authorization code for a GitHub token.
      2. Fetch the GitHub user's profile (+ primary email).
      3. Upsert the User record in the DB.
      4. Issue an RS256 access token (short-lived) and refresh token (long-lived).
      5. Persist the refresh token JTI in the DB.
      6. Attach the refresh token as an HttpOnly cookie on *response*.
      7. Return the access token in the response body.
    """
    # 1 & 2 – GitHub API
    github_token = await _exchange_code(code)
    github_user = await _fetch_github_user(github_token)

    # 3 – DB upsert
    user = await get_or_create_user(
        db=db,
        github_id=str(github_user.id),
        github_username=github_user.login,
        email=github_user.email,
        avatar_url=github_user.avatar_url,
    )

    # 4 – Issue tokens
    access_token, _at_jti, _at_exp = create_access_token(user.id)
    refresh_token, rt_jti, rt_exp = create_refresh_token(user.id)

    # 5 – Persist refresh token
    await store_refresh_token(db, user.id, rt_jti, rt_exp)

    # 6 – HttpOnly cookie
    set_refresh_cookie(response, refresh_token)

    # 7 – Return access token
    expires_in = settings.access_token_expire_minutes * 60
    return AccessTokenResponse(access_token=access_token, expires_in=expires_in)
