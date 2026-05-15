from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, LargeBinary, String, Text, UniqueConstraint
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
    min_profile_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.9)
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_key_source: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_key_source: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discovery_analysis_result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON, persisted across restarts


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
    content_is_remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class ChunkRow(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_project_cluster", "project_id", "cluster_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    material_item_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_is_str: Mapped[bool] = mapped_column(nullable=False)  # True → decode as UTF-8 on read
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RatingRow(Base):
    __tablename__ = "ratings"
    __table_args__ = (Index("ix_ratings_chunk_project_ai_skipped", "chunk_id", "project_id", "is_ai", "skipped"),)

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
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PluginConfigRow(Base):
    __tablename__ = "plugin_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    plugin_name: Mapped[str] = mapped_column(String, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FileManifestRow(Base):
    """Maps on-disk UUID blobs to their user-visible virtual paths."""
    __tablename__ = "file_manifest"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID — on-disk filename
    user_path: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # e.g. "/books/foo.epub"
    original_name: Mapped[str] = mapped_column(String, nullable=False)           # "foo.epub"
    suffix: Mapped[str] = mapped_column(String, nullable=False, default="")      # ".epub"
    is_dir: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DiscoveryRatingRow(Base):
    __tablename__ = "discovery_ratings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(String, nullable=False)
    material_item_id: Mapped[str] = mapped_column(String, nullable=False)
    preference: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PluginBatchStateRow(Base):
    """Persistent state for the batched ingest protocol — one row per (project, plugin)."""
    __tablename__ = "plugin_batch_states"
    __table_args__ = (UniqueConstraint("project_id", "plugin_name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    plugin_name: Mapped[str] = mapped_column(String, nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String, nullable=False, default="idle")  # idle|running|paused|done|error
    fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
