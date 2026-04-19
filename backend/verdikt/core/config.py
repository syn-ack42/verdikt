from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from verdikt.core.models import InferenceConfig


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VERDIKT_", env_nested_delimiter="__")

    data_dir: Path = Field(default_factory=lambda: Path.home() / ".verdikt")
    root_path: str = ""                                        # set VERDIKT_ROOT_PATH for reverse proxy subpath
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    inference: InferenceConfig = Field(default_factory=InferenceConfig)

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
    def user_files_path(self) -> Path:
        return self.data_dir / "user_files"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.projects_path.mkdir(parents=True, exist_ok=True)
        self.user_files_path.mkdir(parents=True, exist_ok=True)
