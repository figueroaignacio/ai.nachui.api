"""
app/users/schemas.py
─────────────────────
Pydantic v2 schemas for the users feature module.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserRead(BaseModel):
    """Public representation of a user returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    github_id: str
    github_username: str
    email: str | None = None
    avatar_url: str | None = None
    created_at: datetime


class UserCreate(BaseModel):
    """Internal schema used when creating a new user from GitHub OAuth data."""

    github_id: str
    github_username: str
    email: str | None = None
    avatar_url: str | None = None
