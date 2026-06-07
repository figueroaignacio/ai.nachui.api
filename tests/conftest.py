"""
tests/conftest.py
──────────────────
Shared pytest fixtures:
  - In-memory SQLite async engine (no real Postgres needed in CI)
  - A shared per-test AsyncSession used by BOTH the app and test assertions
  - RSA key pair generated once per test session
  - AsyncClient wired to the test app
"""

import uuid
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.auth.models import RefreshToken  # noqa: F401 – registers model with Base
from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
from app.users.models import User  # noqa: F401 – registers model with Base

# ContextVar that holds the current test's shared session
_current_session: ContextVar[AsyncSession | None] = ContextVar(
    "_current_session", default=None
)


# ── RSA key pair (session-scoped, generated once) ─────────────────────────────

@pytest.fixture(scope="session")
def rsa_private_key_pem() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture(scope="session")
def rsa_public_key_pem(rsa_private_key_pem: str) -> str:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    private_key = load_pem_private_key(rsa_private_key_pem.encode(), password=None)
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


# ── Settings override ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_settings(rsa_private_key_pem: str, rsa_public_key_pem: str) -> Settings:
    return Settings(
        github_client_id="test-client-id",
        github_client_secret="test-client-secret",
        github_redirect_uri="http://testserver/auth/github/callback",
        jwt_private_key=rsa_private_key_pem,
        jwt_public_key=rsa_public_key_pem,
        jwt_algorithm="RS256",
        access_token_expire_minutes=15,
        refresh_token_expire_days=7,
        database_url="sqlite+aiosqlite:///:memory:",
        frontend_url="http://localhost:3000",
        secret_key="test-secret-key-at-least-32-characters-long",
        cookie_secure=False,  # allow non-HTTPS in tests
        cookie_samesite="lax",
        debug=True,
    )


# ── Async SQLite engine (session-scoped) ──────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Shared per-test session ───────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    One AsyncSession per test, shared between the test body and the FastAPI app
    via the _current_session ContextVar.  Rolls back after each test.
    """
    factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with factory() as session:
        token = _current_session.set(session)
        try:
            yield session
        finally:
            _current_session.reset(token)
            await session.rollback()


# ── FastAPI test app ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_app(test_settings: Settings, db_engine) -> FastAPI:
    """
    Build the app with overridden dependencies so it uses:
      - Shared in-memory SQLite session (same as test body via ContextVar)
      - Test RSA keys via patched settings
    """
    from app.core import config as config_module
    from app.core import security as security_module

    config_module.get_settings.cache_clear()

    def _settings_override() -> Settings:
        return test_settings

    config_module.get_settings = _settings_override  # type: ignore[assignment]
    security_module.settings = test_settings

    from app.main import create_app

    application = create_app()

    async def _db_override() -> AsyncGenerator[AsyncSession, None]:
        """
        Yield the session stored in the ContextVar so that the app and the
        test assertions operate on the same DB transaction.
        After the route handler finishes we flush (not commit) so all ORM
        writes become visible to subsequent queries within the same session.
        """
        session = _current_session.get()
        if session is None:
            # Fallback: create a fresh session (should not happen in tests)
            factory = async_sessionmaker(
                bind=db_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with factory() as s:
                yield s
        else:
            try:
                yield session
            finally:
                await session.flush()  # make writes visible without committing

    application.dependency_overrides[get_db] = _db_override
    return application


@pytest_asyncio.fixture()
async def client(
    test_app: FastAPI, db_session: AsyncSession
) -> AsyncGenerator[AsyncClient, None]:
    """
    AsyncClient wired to the test app.
    Depends on db_session to ensure the shared session is active.
    """
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ── Convenience fixtures ──────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def test_user(db_session: AsyncSession) -> User:
    """Create and persist a test User, rolled back after each test."""
    user = User(
        github_id="12345678",
        github_username="testuser",
        email="test@example.com",
        avatar_url="https://avatars.githubusercontent.com/u/12345678",
    )
    db_session.add(user)
    await db_session.flush()
    return user
