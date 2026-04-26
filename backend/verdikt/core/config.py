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
    jwt_secret: str = Field(default="")             # populated from data_dir/jwt_secret if not set via env

    @model_validator(mode="after")
    def _apply_defaults(self) -> AppConfig:
        if self.users_dir is None:
            object.__setattr__(self, "users_dir", self.data_dir / "users")
        if not self.jwt_secret:
            object.__setattr__(self, "jwt_secret", self._read_or_generate_jwt())
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
