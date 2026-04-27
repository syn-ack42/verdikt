"""Unit tests for inference/resolver.py — no real models loaded."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from verdikt.core.models import Domain, Project
from verdikt.core.config import AppConfig, InferenceConfig
from verdikt.inference.resolver import resolve_embedder, resolve_llm_model


def _config(embedding_model: str = "all-MiniLM-L6-v2", clip_model: str = "openai/clip-vit-base-patch32") -> AppConfig:
    cfg = MagicMock(spec=AppConfig)
    cfg.inference = InferenceConfig(
        embedding_model=embedding_model,
        clip_model=clip_model,
        ollama_model="llama3.1:8b",
        ollama_base_url="http://localhost:11434",
    )
    return cfg


def _project(domain: Domain = Domain.TEXT, embedding_model: str | None = None, llm_model: str | None = None) -> Project:
    return Project(name="Test", domain=domain, embedding_model=embedding_model, llm_model=llm_model)


# ── resolve_embedder ──────────────────────────────────────────────────────────

def test_image_domain_returns_clip_embedder():
    from verdikt.inference.clip_embedder import CLIPEmbedder
    proj = _project(Domain.IMAGE)
    with patch.object(CLIPEmbedder, "__init__", return_value=None):
        emb = resolve_embedder(proj, _config())
    assert isinstance(emb, CLIPEmbedder)


def test_image_domain_explicit_clip_model_used():
    from verdikt.inference.clip_embedder import CLIPEmbedder
    proj = _project(Domain.IMAGE, embedding_model="openai/clip-vit-large-patch14")
    with patch.object(CLIPEmbedder, "__init__", return_value=None) as init:
        resolve_embedder(proj, _config())
    init.assert_called_once_with("openai/clip-vit-large-patch14")


def test_image_domain_ollama_model_raises():
    proj = _project(Domain.IMAGE, embedding_model="nomic-embed-text:latest")
    with pytest.raises(ValueError, match="Ollama does not"):
        resolve_embedder(proj, _config())


def test_text_domain_sentence_transformer():
    from verdikt.inference.embedder import SentenceTransformerEmbedder
    proj = _project(Domain.TEXT)
    with patch.object(SentenceTransformerEmbedder, "__init__", return_value=None):
        emb = resolve_embedder(proj, _config())
    assert isinstance(emb, SentenceTransformerEmbedder)


def test_text_domain_ollama_embedding_model():
    from verdikt.inference.ollama_embedder import OllamaEmbedder
    proj = _project(Domain.TEXT, embedding_model="nomic-embed-text:latest")
    with patch.object(OllamaEmbedder, "__init__", return_value=None):
        emb = resolve_embedder(proj, _config())
    assert isinstance(emb, OllamaEmbedder)


def test_text_domain_clip_name_heuristic_routes_to_clip():
    """Legacy clip model name in text path must still resolve to CLIPEmbedder."""
    from verdikt.inference.clip_embedder import CLIPEmbedder
    proj = _project(Domain.TEXT, embedding_model="clip-ViT-B-32")
    with patch.object(CLIPEmbedder, "__init__", return_value=None):
        emb = resolve_embedder(proj, _config())
    assert isinstance(emb, CLIPEmbedder)


def test_text_domain_global_config_ollama_fallback():
    from verdikt.inference.ollama_embedder import OllamaEmbedder
    proj = _project(Domain.TEXT)
    with patch.object(OllamaEmbedder, "__init__", return_value=None):
        emb = resolve_embedder(proj, _config(embedding_model="nomic-embed-text:latest"))
    assert isinstance(emb, OllamaEmbedder)


# ── resolve_llm_model ────────────────────────────────────────────────────────

def test_resolve_llm_model_uses_project_override():
    proj = _project(llm_model="mistral:7b")
    url, model = resolve_llm_model(proj, _config())
    assert model == "mistral:7b"


def test_resolve_llm_model_falls_back_to_config():
    proj = _project()
    url, model = resolve_llm_model(proj, _config())
    assert model == "llama3.1:8b"
