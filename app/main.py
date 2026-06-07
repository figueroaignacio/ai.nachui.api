"""
app/main.py
────────────
FastAPI application factory.

Responsibilities:
  - Create the FastAPI app with metadata and CORS middleware.
  - Register all feature routers.
  - Expose lifespan events (DB table creation in development).
  - Mount a root health-check endpoint.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.database import Base, engine
from app.users.router import router as users_router

# Import models so SQLAlchemy registers them before create_all
import app.auth.models  # noqa: F401
import app.users.models  # noqa: F401

settings = get_settings()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: create DB tables (idempotent – use Alembic in production).
    Shutdown: dispose the connection pool.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


# ── Application factory ───────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_title,
        version=settings.app_version,
        description="GitHub OAuth authentication API with JWT + refresh token rotation.",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,          # required for HttpOnly cookies
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(auth_router)
    app.include_router(users_router)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["health"], summary="Health check")
    async def health() -> dict:
        return {"status": "ok", "version": settings.app_version}

    return app


# Top-level `app` instance consumed by uvicorn / gunicorn
app = create_app()
