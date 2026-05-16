from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from verdikt.core.models import InferenceConfig


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VERDIKT_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path("/var/lib/verdikt"))
    users_dir: Optional[Path] = Field(default=None)      # defaults to data_dir / "users"
    frontend_dir: Optional[Path] = Field(default=None)   # set to serve built frontend static files
    root_path: str = ""                                  # set VERDIKT_ROOT_PATH for reverse proxy subpath
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    jwt_secret: str = Field(default="")
    # SMTP (optional env-var fallbacks; DB settings via admin UI take precedence)
    smtp_host: Optional[str] = Field(default=None)
    smtp_port: int = Field(default=587)
    smtp_user: Optional[str] = Field(default=None)
    smtp_password: Optional[str] = Field(default=None)
    smtp_from: Optional[str] = Field(default=None)
    smtp_use_tls: bool = Field(default=True)
    # Project creation defaults and chunk-size range constraints
    default_crystallisation_threshold: int = Field(default=10)
    default_chunk_min_size: int = Field(default=600)
    default_chunk_max_size: int = Field(default=800)
    chunk_size_min_lower: int = Field(default=0)    # minimum allowed value for chunk_min_size
    chunk_size_max_upper: int = Field(default=1000) # maximum allowed value for chunk_max_size
    # Background AI preview in rating screen (env: VERDIKT_AI_PREVIEW_TEXT, VERDIKT_AI_PREVIEW_IMAGE)
    ai_preview_text: bool = Field(default=True)
    ai_preview_image: bool = Field(default=False)
    # Public base URL of the app — used in email links, OAuth redirects, etc.
    # Set to the URL users type in their browser, e.g. https://verdikt.example.com
    # (env: VERDIKT_APP_BASE_URL)
    app_base_url: Optional[str] = Field(default=None)
    # OAuth providers (env: VERDIKT_GOOGLE_CLIENT_ID, VERDIKT_GITHUB_CLIENT_ID, etc.)
    google_client_id: Optional[str] = Field(default=None)
    google_client_secret: Optional[str] = Field(default=None)
    github_client_id: Optional[str] = Field(default=None)
    github_client_secret: Optional[str] = Field(default=None)
    # OAuth redirect base — defaults to app_base_url; override only if OAuth callbacks
    # use a different URL than the main app (unusual)
    oauth_redirect_base: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def _apply_defaults(self) -> AppConfig:
        if self.users_dir is None:
            object.__setattr__(self, "users_dir", self.data_dir / "users")
        if not self.jwt_secret:
            object.__setattr__(self, "jwt_secret", self._read_or_generate_jwt())
        # oauth_redirect_base falls back to app_base_url, then to localhost default
        if not self.oauth_redirect_base:
            object.__setattr__(self, "oauth_redirect_base", self.app_base_url or "http://localhost:8765")
        if not self.app_base_url:
            object.__setattr__(self, "app_base_url", self.oauth_redirect_base)
        return self

    def _read_or_generate_jwt(self) -> str:
        path = self.data_dir / "jwt_secret"
        if path.exists():
            return path.read_text().strip()
        secret = secrets.token_hex(32)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secret)
        except OSError:
            pass  # ephemeral secret acceptable when data_dir not yet writable (tests/dev)
        return secret

    # ── Legacy paths (used by CLI and migration script; pre-auth global DB) ──────
    @property
    def db_path(self) -> Path:
        return self.data_dir / "verdikt.db"

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def projects_path(self) -> Path:
        return self.data_dir / "projects"

    def project_materials_path(self, project_id: str) -> Path:
        return self.projects_path / project_id / "materials"

    @property
    def legacy_files_path(self) -> Path:
        return self.data_dir / "user_files"

    # ── Auth DB ──────────────────────────────────────────────────────────────────
    @property
    def auth_db_path(self) -> Path:
        return self.data_dir / "auth.db"

    def user_data_path(self, user_id: str) -> Path:
        return self.users_dir / user_id  # type: ignore[operator]

    def user_db_path(self, user_id: str) -> Path:
        return self.user_data_path(user_id) / "verdikt.db"

    def user_chroma_path(self, user_id: str) -> Path:
        return self.user_data_path(user_id) / "chroma"

    def user_files_path(self, user_id: str) -> Path:
        return self.user_data_path(user_id) / "files"

    def user_projects_path(self, user_id: str) -> Path:
        return self.user_data_path(user_id) / "projects"

    def user_project_materials_path(self, user_id: str, project_id: str) -> Path:
        return self.user_projects_path(user_id) / project_id / "materials"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "verdikt.log"

    def ensure_user_dirs(self, user_id: str) -> None:
        self.user_data_path(user_id).mkdir(parents=True, exist_ok=True)
        self.user_chroma_path(user_id).mkdir(parents=True, exist_ok=True)
        self.user_projects_path(user_id).mkdir(parents=True, exist_ok=True)
        self.user_files_path(user_id).mkdir(parents=True, exist_ok=True)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
