from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_config, require_admin
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import ModelCatalogRow, TokenGrantRow, UserRow

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _user_dict(u: UserRow) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "created_at": u.created_at.isoformat(),
        "is_admin": u.is_admin,
        "is_founding_admin": getattr(u, "is_founding_admin", False),
        "is_blocked": u.is_blocked,
        "daily_token_grant": getattr(u, "daily_token_grant", None),
        "token_grant_expiry_days": getattr(u, "token_grant_expiry_days", 7),
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


@router.post("/users/{user_id}/promote")
def promote_user(
    user_id: str,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    user = session.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = True
    session.commit()
    return _user_dict(user)


@router.post("/users/{user_id}/demote")
def demote_user(
    user_id: str,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot demote yourself")
    user = session.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if getattr(user, "is_founding_admin", False):
        raise HTTPException(status_code=403, detail="The founding admin cannot be demoted")
    user.is_admin = False
    session.commit()
    return _user_dict(user)


class UserLimitsUpdate(BaseModel):
    daily_token_grant: Optional[int] = None
    token_grant_expiry_days: Optional[int] = None


@router.patch("/users/{user_id}/limits")
def update_user_limits(
    user_id: str,
    body: UserLimitsUpdate,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    user = session.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.daily_token_grant is not None:
        user.daily_token_grant = body.daily_token_grant if body.daily_token_grant > 0 else None
    if body.token_grant_expiry_days is not None:
        user.token_grant_expiry_days = body.token_grant_expiry_days
    session.commit()
    return _user_dict(user)


class GrantCreate(BaseModel):
    amount: int
    expires_at: Optional[datetime] = None
    note: Optional[str] = None


@router.post("/users/{user_id}/grants", status_code=201)
def create_grant(
    user_id: str,
    body: GrantCreate,
    admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    user = session.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be positive")
    grant = TokenGrantRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        amount=body.amount,
        granted_at=datetime.now(timezone.utc),
        expires_at=body.expires_at,
        granted_by=admin.id,
        note=body.note,
    )
    session.add(grant)
    session.commit()
    return {
        "id": grant.id,
        "user_id": grant.user_id,
        "amount": grant.amount,
        "granted_at": grant.granted_at.isoformat(),
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "granted_by": grant.granted_by,
        "note": grant.note,
    }


# ── Model catalog ─────────────────────────────────────────────────────────────

def _model_dict(m: ModelCatalogRow) -> dict:
    return {
        "id": m.id,
        "source": m.source,
        "type": m.type,
        "domain": m.domain,
        "enabled": m.enabled,
        "is_default": m.is_default,
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

        # Fetch extra info (context_length, capabilities live in modelinfo / show response)
        context_length: int | None = None
        has_vision = False
        try:
            info = client.show(name)
            ml = getattr(info, "modelinfo", None) or {}
            for key, val in ml.items():
                if "context_length" in key and isinstance(val, int):
                    context_length = val
                    break
            # Newer Ollama versions expose a capabilities list
            caps = getattr(info, "capabilities", None) or []
            if "vision" in caps:
                has_vision = True
        except Exception:
            pass

        # Detect vision capability from model families (available in list() details)
        families: list[str] = []
        if details:
            families = [f.lower() for f in (getattr(details, "families", None) or [])]
        if "clip" in families:
            has_vision = True

        # Auto-classify type and domain for new models
        name_lower = name.lower()
        if "embed" in name_lower:
            auto_type = "embedding"
            auto_domain = "text"   # all current Ollama embedding models are text-only
        elif has_vision:
            auto_type = "llm"
            auto_domain = "any"    # vision LLMs handle both text and image input
        else:
            auto_type = "llm"
            auto_domain = "text"   # text-only LLMs shouldn't appear in image project pickers

        existing = session.get(ModelCatalogRow, name)
        if existing is None:
            session.add(ModelCatalogRow(
                id=name,
                source="ollama",
                type=auto_type,
                domain=auto_domain,
                enabled=False,
                display_name=name,
                description="[vision]" if has_vision else "",
                parameter_size=getattr(details, "parameter_size", None) if details else None,
                context_length=context_length,
                size_bytes=model.size,
                quantization=getattr(details, "quantization_level", None) if details else None,
                synced_at=now,
            ))
        else:
            # Update metadata; preserve admin edits to enabled/type/domain/description
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


class ModelCreate(BaseModel):
    id: str
    type: str
    domain: str = "any"
    display_name: str
    description: str = ""
    source: str = "local"


@router.post("/models")
def create_model(
    body: ModelCreate,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    """Manually register a model (e.g. a sentence-transformer embedding model)."""
    existing = session.get(ModelCatalogRow, body.id)
    if existing is not None:
        existing.type = body.type
        existing.domain = body.domain
        existing.display_name = body.display_name
        existing.description = body.description
        existing.source = body.source
        session.commit()
        return _model_dict(existing)
    row = ModelCatalogRow(
        id=body.id,
        source=body.source,
        type=body.type,
        domain=body.domain,
        enabled=False,
        display_name=body.display_name,
        description=body.description,
    )
    session.add(row)
    session.commit()
    return _model_dict(row)


class ModelUpdate(BaseModel):
    enabled: bool | None = None
    is_default: bool | None = None
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
        if not body.enabled:
            row.is_default = False  # disabled models cannot be the default
    if body.type is not None:
        row.type = body.type
    if body.domain is not None:
        row.domain = body.domain
    if body.display_name is not None:
        row.display_name = body.display_name
    if body.description is not None:
        row.description = body.description
    if body.is_default is not None:
        if body.is_default:
            effective_domain = body.domain or row.domain
            effective_type = body.type or row.type
            # Clear any existing default that overlaps with the effective domain.
            # A model with domain="any" conflicts with any specific domain, and vice-versa.
            overlapping = [effective_domain, "any"] if effective_domain != "any" else ["any"]
            session.query(ModelCatalogRow).filter(
                ModelCatalogRow.type == effective_type,
                ModelCatalogRow.domain.in_(overlapping),
                ModelCatalogRow.id != row.id,
            ).update({"is_default": False})
        row.is_default = body.is_default
    session.commit()
    return _model_dict(row)
