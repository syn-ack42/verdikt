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
    url: Optional[str] = None
    work_title: Optional[str] = None
    author: Optional[str] = None
    work_id: Optional[str] = None
    chapter_position: Optional[int] = None

    # Content — filled by the plugin
    content: bytes | str
    domain: Domain
    content_type: ContentType

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
    chunk_min_words: int = 600
    chunk_max_words: int = 800
    crystallisation_threshold: int = 50
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InferenceConfig(BaseModel):
    ollama_model: str = "llama3.1:8b"
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "all-MiniLM-L6-v2"
