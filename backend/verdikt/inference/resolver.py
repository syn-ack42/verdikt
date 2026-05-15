from __future__ import annotations

from dataclasses import dataclass

from verdikt.core.config import AppConfig
from verdikt.core.models import Domain, Project
from verdikt.inference.base import EmbedderBase

VENICE_BASE_URL = "https://api.venice.ai/api/v1"


@dataclass
class LLMTarget:
    provider: str       # "ollama" | "venice"
    base_url: str
    model: str
    api_key: str | None = None


def _get_venice_key(auth_session) -> str | None:
    from verdikt.storage.auth_orm import SiteSettingsRow
    row = auth_session.get(SiteSettingsRow, "venice.api_key")
    return row.value if row and row.value else None


def resolve_llm_target(project: Project, config: AppConfig, auth_session) -> LLMTarget:
    """Return LLMTarget for the project's LLM, routing to Venice if the model is a Venice catalog entry."""
    model_id = project.llm_model or config.inference.ollama_model
    from verdikt.storage.auth_orm import ModelCatalogRow
    row = auth_session.get(ModelCatalogRow, model_id)
    if row and row.source == "venice":
        api_key = _get_venice_key(auth_session)
        if not api_key:
            raise RuntimeError("Venice API key not configured. Set it in Admin → Model Catalog.")
        return LLMTarget(provider="venice", base_url=VENICE_BASE_URL, model=model_id, api_key=api_key)
    return LLMTarget(provider="ollama", base_url=config.inference.ollama_base_url, model=model_id)


def resolve_llm_model(project: Project, config: AppConfig) -> tuple[str, str]:
    """Return (ollama_base_url, model_name) for LLM calls. Legacy helper; prefer resolve_llm_target."""
    return config.inference.ollama_base_url, (project.llm_model or config.inference.ollama_model)


def resolve_embedder(project: Project, config: AppConfig, auth_session=None) -> EmbedderBase:
    """Return the right embedder for a project.

    When auth_session is provided and the configured embedding model exists in the catalog
    with source="venice", returns a VeniceEmbedder.

    When auth_session is None the Venice catalog check is skipped entirely — the model
    name is passed straight to the Ollama/SentenceTransformer routing below. Callers that
    may have Venice embedding models configured (pipeline, batch_ingest, ai_rating) must
    pass auth_session; omitting it is only safe for Ollama/local models.
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

    # Check if the embedding model is a Venice model
    if auth_session is not None and project.embedding_model:
        from verdikt.storage.auth_orm import ModelCatalogRow
        row = auth_session.get(ModelCatalogRow, project.embedding_model)
        if row and row.source == "venice":
            api_key = _get_venice_key(auth_session)
            if not api_key:
                raise RuntimeError("Venice API key not configured. Set it in Admin → Model Catalog.")
            from verdikt.inference.venice_embedder import VeniceEmbedder
            return VeniceEmbedder(VENICE_BASE_URL, project.embedding_model, api_key)

    from verdikt.inference.embedder import SentenceTransformerEmbedder

    model_name = project.embedding_model or config.inference.embedding_model
    if ":" in model_name:
        from verdikt.inference.ollama_embedder import OllamaEmbedder
        return OllamaEmbedder(model_name, config.inference.ollama_base_url)
    if "clip" in model_name.lower():
        from verdikt.inference.clip_embedder import CLIPEmbedder
        return CLIPEmbedder(model_name)
    return SentenceTransformerEmbedder(model_name)
