from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
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


class ModelCatalogRow(AuthBase):
    __tablename__ = "model_catalog"

    id: Mapped[str] = mapped_column(String, primary_key=True)          # Ollama model name, e.g. "llama3.1:8b"
    source: Mapped[str] = mapped_column(String, nullable=False)        # "ollama" | "local"
    type: Mapped[str] = mapped_column(String, nullable=False)          # "llm" | "embedding"
    domain: Mapped[str] = mapped_column(String, nullable=False, default="any")  # "text"|"image"|"audio"|"any"
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    parameter_size: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    context_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantization: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
