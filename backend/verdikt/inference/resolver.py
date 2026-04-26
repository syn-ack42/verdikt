from __future__ import annotations

from verdikt.core.config import AppConfig
from verdikt.core.models import Project
from verdikt.inference.base import EmbedderBase


def resolve_embedder(project: Project, config: AppConfig) -> EmbedderBase:
    """Return the right embedder for a project, falling back to global config.

    Heuristic: Ollama model names always contain ":" (the tag separator, e.g. "nomic-embed-text:latest").
    Sentence-transformer model names never do (e.g. "all-MiniLM-L6-v2").
    """
    model_name = project.embedding_model or config.inference.embedding_model
    if ":" in model_name:
        from verdikt.inference.ollama_embedder import OllamaEmbedder
        return OllamaEmbedder(model_name, config.inference.ollama_base_url)
    from verdikt.inference.embedder import SentenceTransformerEmbedder
    return SentenceTransformerEmbedder(model_name)


def resolve_llm_model(project: Project, config: AppConfig) -> tuple[str, str]:
    """Return (ollama_base_url, model_name) for LLM calls."""
    return config.inference.ollama_base_url, (project.llm_model or config.inference.ollama_model)
