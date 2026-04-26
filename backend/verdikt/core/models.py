from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Domain(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"


class ContentType(str, Enum):
    PLAIN = "text/plain"
    HTML = "text/html"
    MARKDOWN = "text/markdown"
    EPUB = "application/epub+zip"
    PDF = "application/pdf"
    RTF = "application/rtf"
    JPEG = "image/jpeg"
    PNG = "image/png"
    MP3 = "audio/mpeg"


class PipelinePhase(str, Enum):
    INGESTED = "ingested"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    CLUSTERED = "clustered"
    RATED = "rated"
    CRYSTALLISED = "crystallised"
    EVALUATED = "evaluated"


class MaterialItem(BaseModel):
    """Universal data contract between the plugin layer and the pipeline.

    Plugins fill provenance + content. The pipeline fills everything else.
    This is the stable public API that third-party plugin authors depend on.
    """

    model_config = ConfigDict(use_enum_values=True)

    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str

    # Provenance — filled by the plugin
    source_plugin: str
    source_path: Optional[str] = None  # absolute file path; used as identity key for upserts
    project_seq: Optional[int] = None  # project-scoped sequential number assigned on save
    url: Optional[str] = None
    work_title: Optional[str] = None
    author: Optional[str] = None
    sequence_position: Optional[int] = None  # position within a larger work (chapter, track, etc.)

    # Content — filled by the plugin
    content: bytes | str
    content_hash: Optional[str] = None  # SHA-256 hex of raw content; used to detect changes on re-ingest
    domain: Domain
    content_type: ContentType

    # Plugin-specific metadata — arbitrary JSON, keyed by the plugin (e.g. {"source_updated_at": "2024-03-15"})
    plugin_metadata: dict = Field(default_factory=dict)

    # Pipeline state — managed by the pipeline
    pipeline_phase: PipelinePhase = PipelinePhase.INGESTED
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RatingDimension(BaseModel):
    name: str
    description: str
    weight: float = 1.0


class Project(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    domain: Domain = Domain.TEXT
    rating_dimensions: list[RatingDimension] = Field(default_factory=list)
    chunk_min_size: int = 600   # domain-native units: words for text, seconds for audio, etc.
    chunk_max_size: int = 800
    crystallisation_threshold: int = 50
    min_profile_confidence: float = 0.9
    llm_model: Optional[str] = None        # overrides global config.inference.ollama_model when set
    embedding_model: Optional[str] = None  # overrides global config.inference.embedding_model when set
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Chunk(BaseModel):
    """A rated-sized slice of a MaterialItem. Embedding and clustering operate on chunks."""

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    material_item_id: str
    project_id: str
    content: bytes | str        # str for text domains, bytes for image/audio
    position: int
    size: int                   # domain-native units (words, frames, etc.)
    cluster_id: Optional[int] = None
    embedding_model: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InferenceConfig(BaseModel):
    ollama_model: str = "llama3.1:8b"
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "all-MiniLM-L6-v2"    # default text embedder (sentence-transformers)
    clip_model: str = "clip-ViT-B-32"             # default image embedder (sentence-transformers CLIP)


class Rating(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    chunk_id: str
    material_item_id: str
    dimension_scores: dict[str, float]  # dimension name → 1.0–5.0
    skipped: bool = False
    skip_reason: Optional[str] = None
    is_ai: bool = False  # True = LLM-generated; False = human or confirmed
    explanations: dict[str, str] = Field(default_factory=dict)  # dimension name → one-sentence explanation
    rated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DimensionProfile(BaseModel):
    name: str
    description: str
    summary: str          # LLM-generated preference text for this dimension
    typical_score: float  # mean of user's scores on this dimension


class PreferenceProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    version: int = 1      # increments on each crystallisation
    dimensions: list[DimensionProfile]
    overall_summary: str
    rating_count: int     # number of ratings this profile was derived from
    confirmed_count: int = 0   # AI confirmations accumulated for this version
    score_sum: float = 0.0     # sum of per-confirmation agreement scores (0–1 each)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PluginConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    plugin_name: str
    config: dict
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
