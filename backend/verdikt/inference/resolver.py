from __future__ import annotations

from verdikt.core.config import AppConfig
from verdikt.core.models import Domain, Project
from verdikt.inference.base import EmbedderBase


def resolve_embedder(project: Project, config: AppConfig) -> EmbedderBase:
    """Return the right embedder for a project, falling back to global config.

    Routing rules:
    - Image domain always uses a local CLIP model via SentenceTransformerEmbedder
      (no Ollama image embedding models exist as of now).
    - For text/audio: Ollama model names contain ":" (e.g. "nomic-embed-text:latest");
      sentence-transformer names never do (e.g. "all-MiniLM-L6-v2").
    """
    if project.domain == Domain.IMAGE:
        explicit = project.embedding_model
        if explicit and ":" in explicit:
            raise ValueError(
                f"Embedding model '{explicit}' looks like an Ollama model, but Ollama does not "
                "provide image embedding models. Use a CLIP model such as "
                f"'{config.inference.clip_model}'. Leave the field blank to use the server default."
            )
        from verdikt.inference.clip_embedder import CLIPEmbedder
        return CLIPEmbedder(explicit or config.inference.clip_model)

    from verdikt.inference.embedder import SentenceTransformerEmbedder

    model_name = project.embedding_model or config.inference.embedding_model
    if ":" in model_name:
        from verdikt.inference.ollama_embedder import OllamaEmbedder
        return OllamaEmbedder(model_name, config.inference.ollama_base_url)
    if "clip" in model_name.lower():
        from verdikt.inference.clip_embedder import CLIPEmbedder
        return CLIPEmbedder(model_name)
    return SentenceTransformerEmbedder(model_name)


def resolve_llm_model(project: Project, config: AppConfig) -> tuple[str, str]:
    """Return (ollama_base_url, model_name) for LLM calls."""
    return config.inference.ollama_base_url, (project.llm_model or config.inference.ollama_model)
