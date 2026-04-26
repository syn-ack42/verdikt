from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_config, require_admin
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import ModelCatalogRow, UserRow

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _user_dict(u: UserRow) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "created_at": u.created_at.isoformat(),
        "is_admin": u.is_admin,
        "is_blocked": u.is_blocked,
    }


@router.get("/users")
def list_users(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    return [_user_dict(u) for u in session.query(UserRow).order_by(UserRow.created_at).all()]


@router.post("/users/{user_id}/block")
def block_user(
    user_id: str,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")
    user = session.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_blocked = True
    session.commit()
    return _user_dict(user)


@router.post("/users/{user_id}/unblock")
def unblock_user(
    user_id: str,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    user = session.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_blocked = False
    session.commit()
    return _user_dict(user)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = session.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(user)
    session.commit()

    # Remove user data directory
    config = get_config()
    user_dir = config.user_data_path(user_id)
    if user_dir.exists():
        shutil.rmtree(user_dir)

    return {"ok": True}


# ── Model catalog ─────────────────────────────────────────────────────────────

def _model_dict(m: ModelCatalogRow) -> dict:
    return {
        "id": m.id,
        "source": m.source,
        "type": m.type,
        "domain": m.domain,
        "enabled": m.enabled,
        "display_name": m.display_name,
        "description": m.description,
        "parameter_size": m.parameter_size,
        "context_length": m.context_length,
        "size_bytes": m.size_bytes,
        "quantization": m.quantization,
        "synced_at": m.synced_at.isoformat() if m.synced_at else None,
    }


@router.post("/models/sync")
def sync_models(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> list[dict]:
    """Pull available models from Ollama and upsert into the model catalog."""
    import ollama as _ollama

    config = get_config()
    client = _ollama.Client(host=config.inference.ollama_base_url)

    try:
        response = client.list()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot reach Ollama: {exc}")

    now = datetime.now(timezone.utc)
    for model in response.models:
        name = model.model or model.name
        details = model.details

        # Fetch extra info (context_length lives in modelinfo)
        context_length: int | None = None
        try:
            info = client.show(name)
            ml = getattr(info, "modelinfo", None) or {}
            for key, val in ml.items():
                if "context_length" in key and isinstance(val, int):
                    context_length = val
                    break
        except Exception:
            pass

        existing = session.get(ModelCatalogRow, name)
        if existing is None:
            session.add(ModelCatalogRow(
                id=name,
                source="ollama",
                type="llm",          # admin should correct to "embedding" where appropriate
                domain="any",
                enabled=False,
                display_name=name,
                description="",
                parameter_size=getattr(details, "parameter_size", None) if details else None,
                context_length=context_length,
                size_bytes=model.size,
                quantization=getattr(details, "quantization_level", None) if details else None,
                synced_at=now,
            ))
        else:
            # Update metadata but preserve admin edits to enabled/type/domain/description
            existing.parameter_size = getattr(details, "parameter_size", None) if details else None
            existing.context_length = context_length
            existing.size_bytes = model.size
            existing.quantization = getattr(details, "quantization_level", None) if details else None
            existing.synced_at = now

    session.commit()
    rows = session.query(ModelCatalogRow).order_by(ModelCatalogRow.type, ModelCatalogRow.id).all()
    return [_model_dict(r) for r in rows]


@router.get("/models")
def list_models(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> list[dict]:
    rows = session.query(ModelCatalogRow).order_by(ModelCatalogRow.type, ModelCatalogRow.id).all()
    return [_model_dict(r) for r in rows]


class ModelUpdate(BaseModel):
    enabled: bool | None = None
    type: str | None = None
    domain: str | None = None
    display_name: str | None = None
    description: str | None = None


@router.patch("/models/{model_id:path}")
def update_model(
    model_id: str,
    body: ModelUpdate,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(ModelCatalogRow, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.type is not None:
        row.type = body.type
    if body.domain is not None:
        row.domain = body.domain
    if body.display_name is not None:
        row.display_name = body.display_name
    if body.description is not None:
        row.description = body.description
    session.commit()
    return _model_dict(row)
