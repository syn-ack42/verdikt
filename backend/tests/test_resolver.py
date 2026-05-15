"""Unit tests for inference/resolver.py — no real models loaded."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from verdikt.core.models import Domain, Project
from verdikt.core.config import AppConfig, InferenceConfig
from verdikt.inference.resolver import LLMTarget, resolve_embedder, resolve_llm_model, resolve_llm_target
from verdikt.storage.auth_orm import ModelCatalogRow, SiteSettingsRow


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


# ── resolve_llm_target ────────────────────────────────────────────────────────

def _auth_session(model_id: str, source: str = "ollama", venice_key: str | None = None) -> MagicMock:
    """Build a mock auth session that returns a catalog row and optional Venice key."""
    catalog_row = MagicMock(spec=ModelCatalogRow)
    catalog_row.source = source

    key_row = MagicMock(spec=SiteSettingsRow)
    key_row.value = venice_key

    session = MagicMock()
    def _get(cls, pk):
        if cls is ModelCatalogRow:
            return catalog_row
        if cls is SiteSettingsRow:
            return key_row if venice_key is not None else None
        return None
    session.get.side_effect = _get
    return session


def test_resolve_llm_target_ollama():
    proj = _project(llm_model="mistral:7b")
    session = _auth_session("mistral:7b", source="ollama")
    target = resolve_llm_target(proj, _config(), session)
    assert target.provider == "ollama"
    assert target.model == "mistral:7b"
    assert target.api_key is None


def test_resolve_llm_target_venice():
    proj = _project(llm_model="llama-3.3-70b")
    session = _auth_session("llama-3.3-70b", source="venice", venice_key="sk-test-key")
    target = resolve_llm_target(proj, _config(), session)
    assert target.provider == "venice"
    assert target.model == "llama-3.3-70b"
    assert target.api_key == "sk-test-key"
    assert "venice.ai" in target.base_url


def test_resolve_llm_target_venice_missing_key_raises():
    proj = _project(llm_model="llama-3.3-70b")
    session = _auth_session("llama-3.3-70b", source="venice", venice_key=None)
    with pytest.raises(RuntimeError, match="Venice API key not configured"):
        resolve_llm_target(proj, _config(), session)


def test_resolve_llm_target_falls_back_to_config():
    proj = _project()  # no llm_model override
    session = _auth_session("llama3.1:8b", source="ollama")
    target = resolve_llm_target(proj, _config(), session)
    assert target.provider == "ollama"
    assert target.model == "llama3.1:8b"


# ── resolve_embedder (Venice path) ────────────────────────────────────────────

def test_resolve_embedder_venice_embedding_model():
    from verdikt.inference.venice_embedder import VeniceEmbedder
    proj = _project(Domain.TEXT, embedding_model="text-embedding-bge-m3")

    catalog_row = MagicMock(spec=ModelCatalogRow)
    catalog_row.source = "venice"
    key_row = MagicMock(spec=SiteSettingsRow)
    key_row.value = "sk-test"
    session = MagicMock()
    def _get(cls, pk):
        return catalog_row if cls is ModelCatalogRow else key_row
    session.get.side_effect = _get

    with patch.object(VeniceEmbedder, "__init__", return_value=None):
        emb = resolve_embedder(proj, _config(), session)
    assert isinstance(emb, VeniceEmbedder)


def test_resolve_embedder_venice_missing_key_raises():
    proj = _project(Domain.TEXT, embedding_model="text-embedding-bge-m3")

    catalog_row = MagicMock(spec=ModelCatalogRow)
    catalog_row.source = "venice"
    session = MagicMock()
    def _get(cls, pk):
        if cls is ModelCatalogRow:
            return catalog_row
        return None  # no key row
    session.get.side_effect = _get

    with pytest.raises(RuntimeError, match="Venice API key not configured"):
        resolve_embedder(proj, _config(), session)


def test_resolve_embedder_no_auth_session_skips_venice_check():
    """When auth_session is None the Venice catalog check is bypassed — falls through to local routing."""
    from verdikt.inference.embedder import SentenceTransformerEmbedder
    proj = _project(Domain.TEXT, embedding_model="all-MiniLM-L6-v2")
    with patch.object(SentenceTransformerEmbedder, "__init__", return_value=None):
        emb = resolve_embedder(proj, _config())  # no auth_session
    assert isinstance(emb, SentenceTransformerEmbedder)
