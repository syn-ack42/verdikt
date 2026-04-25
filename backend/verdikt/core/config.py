from __future__ import annotations

import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from verdikt.core.models import InferenceConfig

_JWT_SECRET_FILE = Path.home() / ".verdikt" / "jwt_secret"


def _load_or_generate_jwt_secret() -> str:
    if _JWT_SECRET_FILE.exists():
        return _JWT_SECRET_FILE.read_text().strip()
    secret = secrets.token_hex(32)
    _JWT_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    _JWT_SECRET_FILE.write_text(secret)
    return secret


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VERDIKT_", env_nested_delimiter="__")

    data_dir: Path = Field(default_factory=lambda: Path.home() / ".verdikt")
    root_path: str = ""                                        # set VERDIKT_ROOT_PATH for reverse proxy subpath
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    jwt_secret: str = Field(default_factory=_load_or_generate_jwt_secret)

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

    @property
    def users_dir(self) -> Path:
        return self.data_dir / "users"

    def user_data_path(self, user_id: str) -> Path:
        return self.users_dir / user_id

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
        self.users_dir.mkdir(parents=True, exist_ok=True)
