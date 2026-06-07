"""
app/auth/models.py
───────────────────
RefreshToken ORM model. FKs into users.id from the users module.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # jti matches the `jti` claim inside the signed JWT
    jti: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship back to User (string ref avoids import-time cycle)
    user: Mapped["User"] = relationship(  # noqa: F821
        "User", back_populates="refresh_tokens"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RefreshToken jti={self.jti!r} revoked={self.revoked}>"
