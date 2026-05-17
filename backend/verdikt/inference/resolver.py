from __future__ import annotations

from dataclasses import dataclass

from verdikt.core.config import AppConfig
from verdikt.core.models import Domain, Project
from verdikt.inference.base import EmbedderBase

VENICE_BASE_URL = "https://api.venice.ai/api/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class LLMTarget:
    provider: str       # "ollama" | "venice" | "openrouter"
    base_url: str
    model: str
    api_key: str | None = None


def _get_venice_key(auth_session) -> str | None:
    from verdikt.storage.auth_orm import SiteSettingsRow
    row = auth_session.get(SiteSettingsRow, "venice.api_key")
    return row.value if row and row.value else None


def _get_openrouter_key(auth_session) -> str | None:
    from verdikt.storage.auth_orm import SiteSettingsRow
    row = auth_session.get(SiteSettingsRow, "openrouter.api_key")
    return row.value if row and row.value else None


def _get_ollama_key(auth_session) -> str | None:
    from verdikt.storage.auth_orm import SiteSettingsRow
    row = auth_session.get(SiteSettingsRow, "ollama.api_key")
    return row.value if row and row.value else None


def _decrypt_user_key(encrypted: str, jwt_secret: str, info: bytes) -> str:
    import base64
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    wrap_key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=info,
    ).derive(jwt_secret.encode())
    raw = Fernet(base64.urlsafe_b64encode(wrap_key)).decrypt(encrypted.encode())
    return raw.decode()


def _get_user_venice_key(user_id: str, auth_session) -> str | None:
    """Return the decrypted personal Venice API key for a user, or None if not set."""
    from verdikt.storage.auth_orm import UserRow
    row = auth_session.get(UserRow, user_id)
    if not row or not getattr(row, "venice_api_key_enc", None):
        return None
    try:
        from verdikt.api.deps import get_config
        config = get_config()
        return _decrypt_user_key(row.venice_api_key_enc, config.jwt_secret, b"verdikt-user-venice-key-wrap-v1")
    except Exception:
        return None


def _get_user_openrouter_key(user_id: str, auth_session) -> str | None:
    """Return the decrypted personal OpenRouter API key for a user, or None if not set."""
    from verdikt.storage.auth_orm import UserRow
    row = auth_session.get(UserRow, user_id)
    if not row or not getattr(row, "openrouter_api_key_enc", None):
        return None
    try:
        from verdikt.api.deps import get_config
        config = get_config()
        return _decrypt_user_key(row.openrouter_api_key_enc, config.jwt_secret, b"verdikt-user-openrouter-key-wrap-v1")
    except Exception:
        return None


def resolve_llm_target(project: Project, config: AppConfig, auth_session, user_id: str | None = None) -> LLMTarget:
    """Return LLMTarget for the project's LLM.

    If project.llm_key_source == "personal" and user_id is provided, uses the user's
    own provider API key (Venice or OpenRouter, determined by model source).
    Raises if the key is not configured.

    Otherwise routes to Venice/OpenRouter (site key) or Ollama based on ModelCatalogRow.source.
    """
    model_id = project.llm_model or config.inference.ollama_model

    from verdikt.storage.auth_orm import ModelCatalogRow
    row = auth_session.get(ModelCatalogRow, model_id)
    model_source = row.source if row else "ollama"

    if getattr(project, "llm_key_source", None) == "personal":
        if not user_id:
            raise RuntimeError("Personal API key requested but no user context available")
        if model_source == "openrouter":
            api_key = _get_user_openrouter_key(user_id, auth_session)
            if not api_key:
                raise RuntimeError("No personal OpenRouter API key configured. Add it in Account Settings.")
            return LLMTarget(provider="openrouter", base_url=OPENROUTER_BASE_URL, model=model_id, api_key=api_key)
        else:
            api_key = _get_user_venice_key(user_id, auth_session)
            if not api_key:
                raise RuntimeError("No personal Venice API key configured. Add it in Account Settings.")
            return LLMTarget(provider="venice", base_url=VENICE_BASE_URL, model=model_id, api_key=api_key)

    if model_source == "venice":
        api_key = _get_venice_key(auth_session)
        if not api_key:
            raise RuntimeError("Venice API key not configured. Set it in Admin → Model Catalog.")
        return LLMTarget(provider="venice", base_url=VENICE_BASE_URL, model=model_id, api_key=api_key)
    if model_source == "openrouter":
        api_key = _get_openrouter_key(auth_session)
        if not api_key:
            raise RuntimeError("OpenRouter API key not configured. Set it in Admin → Model Catalog.")
        return LLMTarget(provider="openrouter", base_url=OPENROUTER_BASE_URL, model=model_id, api_key=api_key)
    return LLMTarget(provider="ollama", base_url=config.inference.ollama_base_url, model=model_id,
                     api_key=_get_ollama_key(auth_session))


def resolve_llm_model(project: Project, config: AppConfig) -> tuple[str, str]:
    """Return (ollama_base_url, model_name) for LLM calls. Legacy helper; prefer resolve_llm_target."""
    return config.inference.ollama_base_url, (project.llm_model or config.inference.ollama_model)


def resolve_embedder(project: Project, config: AppConfig, auth_session=None, user_id: str | None = None) -> EmbedderBase:
    """Return the right embedder for a project.

    If project.embedding_key_source == "personal" and user_id is provided, uses the
    user's own Venice API key (no fallback to site key). Raises if key is not configured.

    When auth_session is provided and the configured embedding model exists in the catalog
    with source="venice", returns a VeniceEmbedder using the site key.

    When auth_session is None the Venice catalog check is skipped entirely — the model
    name is passed straight to the Ollama/SentenceTransformer routing below.
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

    # Personal Venice key path
    if getattr(project, "embedding_key_source", None) == "personal" and auth_session is not None:
        if not user_id:
            raise RuntimeError("Personal Venice key requested but no user context available")
        model_name = project.embedding_model or config.inference.embedding_model
        api_key = _get_user_venice_key(user_id, auth_session)
        if not api_key:
            raise RuntimeError(
                "No personal Venice API key configured. Add it in Account Settings."
            )
        from verdikt.inference.venice_embedder import VeniceEmbedder
        return VeniceEmbedder(VENICE_BASE_URL, model_name, api_key)

    # Site key Venice path
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
        return OllamaEmbedder(model_name, config.inference.ollama_base_url,
                              api_key=_get_ollama_key(auth_session) if auth_session else None)
    if "clip" in model_name.lower():
        from verdikt.inference.clip_embedder import CLIPEmbedder
        return CLIPEmbedder(model_name)
    return SentenceTransformerEmbedder(model_name)
