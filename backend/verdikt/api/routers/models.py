from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_current_user
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import ModelCatalogRow

router = APIRouter(prefix="/api/models", tags=["models"])

_LLM_DOMAINS = ("text", "image")


@router.get("/defaults")
def get_model_defaults(
    _user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_auth_session),
) -> dict:
    """Return the admin-designated default LLM model per domain."""
    rows = (
        session.query(ModelCatalogRow)
        .filter(
            ModelCatalogRow.type == "llm",
            ModelCatalogRow.enabled == True,  # noqa: E712
            ModelCatalogRow.is_default == True,  # noqa: E712
        )
        .all()
    )
    # A model with domain="any" can serve as default for both text and image
    defaults: dict[str, str | None] = {d: None for d in _LLM_DOMAINS}
    for row in rows:
        if row.domain == "any":
            for d in _LLM_DOMAINS:
                if defaults[d] is None:
                    defaults[d] = row.id
        elif row.domain in defaults:
            defaults[row.domain] = row.id
    return {"llm_by_domain": defaults}


@router.get("/domain-availability")
def get_domain_availability(
    _user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_auth_session),
) -> dict:
    """Return which domains have at least one enabled LLM model."""
    rows = (
        session.query(ModelCatalogRow.domain)
        .filter(
            ModelCatalogRow.type == "llm",
            ModelCatalogRow.enabled == True,  # noqa: E712
        )
        .distinct()
        .all()
    )
    available_domains: set[str] = set()
    for (domain,) in rows:
        if domain == "any":
            available_domains.update(_LLM_DOMAINS)
        else:
            available_domains.add(domain)
    return {d: d in available_domains for d in _LLM_DOMAINS}


@router.get("")
def list_enabled_models(
    type: str | None = None,
    domain: str | None = None,
    _user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_auth_session),
) -> list[dict]:
    """Return admin-enabled models, optionally filtered by type and/or domain."""
    q = session.query(ModelCatalogRow).filter(ModelCatalogRow.enabled == True)  # noqa: E712
    if type is not None:
        q = q.filter(ModelCatalogRow.type == type)
    if domain is not None:
        q = q.filter(ModelCatalogRow.domain.in_([domain, "any"]))
    rows = q.order_by(ModelCatalogRow.type, ModelCatalogRow.id).all()
    return [
        {
            "id": r.id,
            "type": r.type,
            "domain": r.domain,
            "source": r.source,
            "is_default": r.is_default,
            "display_name": r.display_name,
            "description": r.description,
            "parameter_size": r.parameter_size,
            "context_length": r.context_length,
            "quantization": r.quantization,
            "input_cost_usd_per_mtok": r.input_cost_usd_per_mtok,
            "output_cost_usd_per_mtok": r.output_cost_usd_per_mtok,
            "privacy": r.privacy,
        }
        for r in rows
    ]
