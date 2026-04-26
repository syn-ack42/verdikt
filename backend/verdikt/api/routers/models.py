from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_current_user
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import ModelCatalogRow

router = APIRouter(prefix="/api/models", tags=["models"])


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
            "display_name": r.display_name,
            "description": r.description,
            "parameter_size": r.parameter_size,
            "context_length": r.context_length,
            "quantization": r.quantization,
        }
        for r in rows
    ]
