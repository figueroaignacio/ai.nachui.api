"""
app/core/config.py
──────────────────
Application-wide settings loaded from environment variables / .env file.
Uses pydantic-settings v2 with an @lru_cache singleton.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to the project root (two levels up from this file),
# so the file is found regardless of which directory the server is launched from.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── GitHub OAuth ──────────────────────────────────────────────────────────
    github_client_id: str = "changeme"
    github_client_secret: str = "changeme"
    github_redirect_uri: str = "http://localhost:8000/auth/github/callback"

    # ── JWT (RSA PEM strings; embed literal \n in .env, they are expanded here)
    jwt_private_key: str = ""
    jwt_public_key: str = ""
    jwt_algorithm: str = "RS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/auth_db"

    # ── CORS / Frontend ───────────────────────────────────────────────────────
    frontend_url: str = "http://localhost:3000"

    # ── Cookie / state signing ────────────────────────────────────────────────
    secret_key: str = "changeme-secret-key-at-least-32-chars"

    # ── Cookie flags ──────────────────────────────────────────────────────────
    cookie_secure: bool = True
    cookie_samesite: str = "lax"

    # ── App metadata ──────────────────────────────────────────────────────────
    app_title: str = "Auth API"
    app_version: str = "0.1.0"
    debug: bool = False

    @computed_field  # type: ignore[misc]
    @property
    def allowed_origins(self) -> list[str]:
        return [self.frontend_url, "http://localhost:3000", "http://localhost:8000"]

    @computed_field  # type: ignore[misc]
    @property
    def rsa_private_key(self) -> str:
        """Return the RSA private key with real newlines."""
        return self.jwt_private_key.replace("\\n", "\n")

    @computed_field  # type: ignore[misc]
    @property
    def rsa_public_key(self) -> str:
        """Return the RSA public key with real newlines."""
        return self.jwt_public_key.replace("\\n", "\n")


@lru_cache
def get_settings() -> Settings:
    """Cached singleton – call this anywhere to get the same Settings object."""
    return Settings()
