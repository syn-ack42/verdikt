from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    domain: Mapped[str] = mapped_column(String, nullable=False)
    rating_dimensions: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    chunk_min_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_max_size: Mapped[int] = mapped_column(Integer, nullable=False)
    crystallisation_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MaterialItemRow(Base):
    __tablename__ = "material_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_plugin: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    project_seq: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    work_title: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    sequence_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_is_bytes: Mapped[bool] = mapped_column(nullable=False)
    domain: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    pipeline_phase: Mapped[str] = mapped_column(String, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plugin_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class ChunkRow(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    material_item_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_is_str: Mapped[bool] = mapped_column(nullable=False)  # True → decode as UTF-8 on read
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RatingRow(Base):
    __tablename__ = "ratings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    material_item_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    dimension_scores: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    is_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explanations: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON dict[str, str]
    rated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PreferenceProfileRow(Base):
    __tablename__ = "preference_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    dimensions_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list[DimensionProfile]
    overall_summary: Mapped[str] = mapped_column(Text, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PluginConfigRow(Base):
    __tablename__ = "plugin_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    plugin_name: Mapped[str] = mapped_column(String, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
