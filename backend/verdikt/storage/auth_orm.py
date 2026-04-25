from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AuthBase(DeclarativeBase):
    pass


class UserRow(AuthBase):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    argon2_hash: Mapped[str] = mapped_column(String, nullable=False)
    kdf_salt: Mapped[str] = mapped_column(String, nullable=False)  # hex-encoded 32-byte salt for key derivation
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
