from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.auth.models  # noqa: F401
import app.chats.models  # noqa: F401
import app.users.models  # noqa: F401
from app.auth.router import router as auth_router
from app.chats.router import router as chats_router
from app.core.config import get_settings
from app.core.database import Base, engine
from app.users.router import router as users_router

settings = get_settings()


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


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_title,
        version=settings.app_version,
        description="GitHub OAuth authentication API with JWT + refresh token rotation.",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(chats_router)

    @app.get("/health", tags=["health"], summary="Health check")
    async def health() -> dict:
        return {"status": "ok", "version": settings.app_version}

    return app


app = create_app()
