from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VERDIKT_")

    data_dir: Path = Field(default_factory=lambda: Path.home() / ".verdikt")

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

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.projects_path.mkdir(parents=True, exist_ok=True)
