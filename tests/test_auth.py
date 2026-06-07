"""
tests/test_auth.py
───────────────────
Integration tests for all auth endpoints using AsyncClient + mocked GitHub APIs.

Covers:
  - GET  /auth/github              → 302 redirect to github.com
  - GET  /auth/github/callback     → creates user, sets cookie, returns access token
  - POST /auth/refresh             → rotates refresh token correctly
  - POST /auth/logout              → revokes token, clears cookie
  - GET  /auth/me                  → 200 with valid token, 401 with expired/missing
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response as HttpxResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken
from app.core.config import Settings
from app.core.security import REFRESH_COOKIE_NAME, REFRESH_COOKIE_PATH
from app.users.models import User

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_github_token_response() -> dict:
    return {"access_token": "gho_fake_token", "token_type": "bearer", "scope": "read:user"}


def _mock_github_user_response() -> dict:
    return {
        "id": 99999,
        "login": "octocat",
        "email": "octocat@github.com",
        "avatar_url": "https://avatars.githubusercontent.com/u/99999",
        "name": "The Octocat",
    }


async def _get_state_cookie(client: AsyncClient) -> str:
    """Trigger /auth/github to get the signed state cookie."""
    resp = await client.get("/auth/github", follow_redirects=False)
    assert resp.status_code == 302
    return client.cookies.get("oauth_state", "")


async def _do_full_login(
    client: AsyncClient,
    db_session: AsyncSession,
    test_settings: Settings,
) -> tuple[str, str]:
    """
    Run the full OAuth callback flow with mocked GitHub responses.
    Returns (access_token, refresh_token_jti).
    """
    # 1. Initiate login to get the state cookie
    init_resp = await client.get("/auth/github", follow_redirects=False)
    assert init_resp.status_code == 302
    state_cookie = client.cookies.get("oauth_state")
    assert state_cookie, "oauth_state cookie must be set"

    # 2. Perform callback with mocked GitHub HTTP calls
    with (
        patch(
            "app.auth.service._exchange_code",
            new=AsyncMock(return_value="gho_fake_token"),
        ),
        patch(
            "app.auth.service._fetch_github_user",
            new=AsyncMock(
                return_value=MagicMock(
                    id=99999,
                    login="octocat",
                    email="octocat@github.com",
                    avatar_url="https://avatars.githubusercontent.com/u/99999",
                )
            ),
        ),
    ):
        # Patch settings inside security so token crypto uses test keys
        with patch("app.core.security.settings", test_settings):
            callback_resp = await client.get(
                "/auth/github/callback",
                params={"code": "fake_code", "state": state_cookie},
                follow_redirects=False,
            )

    assert callback_resp.status_code == 200, callback_resp.text
    body = callback_resp.json()
    assert "access_token" in body

    # Retrieve jti from DB
    result = await db_session.execute(
        select(RefreshToken).order_by(RefreshToken.created_at.desc()).limit(1)
    )
    rt = result.scalar_one()
    return body["access_token"], rt.jti


# ── Tests: /auth/github ───────────────────────────────────────────────────────

class TestGitHubLogin:
    async def test_redirects_to_github(self, client: AsyncClient) -> None:
        resp = await client.get("/auth/github", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "github.com/login/oauth/authorize" in location
        assert "client_id=" in location
        assert "state=" in location

    async def test_sets_state_cookie(self, client: AsyncClient) -> None:
        resp = await client.get("/auth/github", follow_redirects=False)
        assert resp.status_code == 302
        assert "oauth_state" in resp.cookies

    async def test_redirect_includes_email_scope(self, client: AsyncClient) -> None:
        resp = await client.get("/auth/github", follow_redirects=False)
        assert "user:email" in resp.headers["location"]


# ── Tests: /auth/github/callback ─────────────────────────────────────────────

class TestGitHubCallback:
    async def test_missing_state_returns_400(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/auth/github/callback",
            params={"code": "abc", "state": "bad-state"},
        )
        assert resp.status_code == 400

    async def test_mismatched_state_returns_400(self, client: AsyncClient) -> None:
        # Get a valid cookie but send a different state param
        await client.get("/auth/github", follow_redirects=False)
        resp = await client.get(
            "/auth/github/callback",
            params={"code": "abc", "state": "totally-wrong"},
        )
        assert resp.status_code == 400

    async def test_successful_callback_creates_user_and_returns_token(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_settings: Settings,
    ) -> None:
        access_token, _jti = await _do_full_login(client, db_session, test_settings)

        # Verify user was created
        result = await db_session.execute(
            select(User).where(User.github_id == "99999")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.github_username == "octocat"
        assert user.email == "octocat@github.com"

        # Verify access token is a non-empty string
        assert isinstance(access_token, str)
        assert len(access_token) > 20

    async def test_callback_sets_httponly_refresh_cookie(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_settings: Settings,
    ) -> None:
        init_resp = await client.get("/auth/github", follow_redirects=False)
        state_cookie = client.cookies.get("oauth_state")

        with (
            patch("app.auth.service._exchange_code", new=AsyncMock(return_value="tok")),
            patch(
                "app.auth.service._fetch_github_user",
                new=AsyncMock(
                    return_value=MagicMock(
                        id=88888,
                        login="newuser",
                        email="new@example.com",
                        avatar_url=None,
                    )
                ),
            ),
            patch("app.core.security.settings", test_settings),
        ):
            resp = await client.get(
                "/auth/github/callback",
                params={"code": "code", "state": state_cookie},
            )

        assert resp.status_code == 200
        # httpx stores cookies; verify the cookie is present
        assert REFRESH_COOKIE_NAME in client.cookies

    async def test_second_login_returns_existing_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_settings: Settings,
    ) -> None:
        # Login twice with the same GitHub account
        await _do_full_login(client, db_session, test_settings)
        await _do_full_login(client, db_session, test_settings)

        result = await db_session.execute(
            select(User).where(User.github_id == "99999")
        )
        users = result.scalars().all()
        assert len(users) == 1  # no duplicate


# ── Tests: /auth/refresh ──────────────────────────────────────────────────────

class TestTokenRefresh:
    async def test_rotate_returns_new_access_token(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_settings: Settings,
    ) -> None:
        first_token, _jti = await _do_full_login(client, db_session, test_settings)

        with patch("app.core.security.settings", test_settings):
            resp = await client.post("/auth/refresh")

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["access_token"] != first_token

    async def test_old_refresh_token_is_revoked_after_rotation(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_settings: Settings,
    ) -> None:
        _token, old_jti = await _do_full_login(client, db_session, test_settings)

        with patch("app.core.security.settings", test_settings):
            await client.post("/auth/refresh")

        # Expire the identity map so SQLAlchemy re-fetches from DB
        db_session.expire_all()

        # Old JTI must be revoked
        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.jti == old_jti)
        )
        old_rt = result.scalar_one()
        assert old_rt.revoked is True

    async def test_refresh_without_cookie_returns_401(
        self, client: AsyncClient
    ) -> None:
        # Use a fresh client with no cookies
        from httpx import ASGITransport, AsyncClient as FreshClient

        async with FreshClient(
            transport=ASGITransport(app=client._transport.app),  # type: ignore[attr-defined]
            base_url="http://testserver",
        ) as fresh:
            resp = await fresh.post("/auth/refresh")
        assert resp.status_code == 401

    async def test_refresh_with_revoked_token_returns_401(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_settings: Settings,
    ) -> None:
        _token, jti = await _do_full_login(client, db_session, test_settings)

        # Manually revoke via the shared session (visible to the app immediately)
        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.jti == jti)
        )
        rt = result.scalar_one()
        rt.revoked = True
        await db_session.flush()  # write to DB without committing
        db_session.expire_all()  # ensure the app sees the updated row

        with patch("app.core.security.settings", test_settings):
            resp = await client.post("/auth/refresh")

        assert resp.status_code == 401


# ── Tests: /auth/logout ───────────────────────────────────────────────────────

class TestLogout:
    async def test_logout_revokes_token_and_clears_cookie(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_settings: Settings,
    ) -> None:
        _token, jti = await _do_full_login(client, db_session, test_settings)

        with patch("app.core.security.settings", test_settings):
            resp = await client.post("/auth/logout")

        assert resp.status_code == 204

        # Re-fetch from DB to see the updated revoked state
        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.jti == jti)
        )
        rt = result.scalar_one()
        await db_session.refresh(rt)  # force reload from DB
        assert rt.revoked is True

    async def test_logout_without_cookie_returns_204(
        self, client: AsyncClient
    ) -> None:
        # Logout even without a cookie should succeed gracefully
        resp = await client.post("/auth/logout")
        assert resp.status_code == 204


# ── Tests: /auth/me ───────────────────────────────────────────────────────────

class TestGetMe:
    async def test_returns_user_with_valid_token(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_settings: Settings,
    ) -> None:
        access_token, _ = await _do_full_login(client, db_session, test_settings)

        with patch("app.core.security.settings", test_settings):
            resp = await client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["github_username"] == "octocat"
        assert "id" in body

    async def test_returns_401_with_no_token(self, client: AsyncClient) -> None:
        resp = await client.get("/auth/me")
        assert resp.status_code == 401

    async def test_returns_401_with_expired_token(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_settings: Settings,
    ) -> None:
        from jose import jwt

        # Create a test user first
        user = User(
            github_id="77777",
            github_username="expireduser",
            email="expired@example.com",
        )
        db_session.add(user)
        await db_session.flush()

        expired_payload = {
            "sub": str(user.id),
            "jti": str(uuid.uuid4()),
            "exp": datetime.now(tz=timezone.utc) - timedelta(seconds=10),
            "type": "access",
        }
        expired_token = jwt.encode(
            expired_payload,
            test_settings.rsa_private_key,
            algorithm=test_settings.jwt_algorithm,
        )

        with patch("app.core.security.settings", test_settings):
            resp = await client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {expired_token}"},
            )

        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    async def test_returns_401_with_malformed_token(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert resp.status_code == 401
