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
    argon2_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # null for OAuth users
    kdf_salt: Mapped[Optional[str]] = mapped_column(String, nullable=True)       # null for OAuth users
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_founding_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Email confirmation (True for admin-created users and OAuth users; False until confirmed for self-registered)
    email_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Forced password change on first login (set for admin-created users)
    force_password_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Token budget settings (null daily_token_grant = use site default or unlimited)
    daily_token_grant: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_grant_expiry_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    # Per-user storage limit in bytes (null = use site default)
    storage_limit_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # OAuth identity
    oauth_provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    oauth_provider_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    oauth_db_key_enc: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class TokenUsageRow(AuthBase):
    __tablename__ = "token_usage"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "ai_rating"|"crystallise"|"preview"
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TokenGrantRow(AuthBase):
    __tablename__ = "token_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[str] = mapped_column(String, nullable=False)  # "system_daily" | admin_user_id
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class EmailConfirmationRow(AuthBase):
    __tablename__ = "email_confirmations"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SiteSettingsRow(AuthBase):
    """Key-value store for site-wide configuration (SMTP, default limits, etc.)."""
    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(String, nullable=True)


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
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
