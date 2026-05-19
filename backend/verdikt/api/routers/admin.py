from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_config, require_admin
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import ModelCatalogRow, SiteSettingsRow, TokenGrantRow, TokenUsageRow, UserRow

router = APIRouter(prefix="/api/admin", tags=["admin"])
_ph = PasswordHasher()

from verdikt.inference.prompts import PROMPT_KEYS as _PROMPT_KEYS

_DEFAULT_SETTINGS: dict[str, str] = {
    "default_storage_limit_mb": "10",
    "default_daily_token_grant": "",          # empty = unlimited
    "default_token_grant_expiry_days": "7",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_use_tls": "true",
    **_PROMPT_KEYS,
}


def _user_dict(u: UserRow) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "created_at": u.created_at.isoformat(),
        "is_admin": u.is_admin,
        "is_founding_admin": getattr(u, "is_founding_admin", False),
        "is_blocked": u.is_blocked,
        "email_confirmed": getattr(u, "email_confirmed", True),
        "force_password_change": getattr(u, "force_password_change", False),
        "daily_token_grant": getattr(u, "daily_token_grant", None),
        "token_grant_expiry_days": getattr(u, "token_grant_expiry_days", 7),
        "storage_limit_bytes": getattr(u, "storage_limit_bytes", None),
    }


# ── Users ──────────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    return [_user_dict(u) for u in session.query(UserRow).order_by(UserRow.created_at).all()]


class AdminCreateUser(BaseModel):
    email: EmailStr
    password: str


@router.post("/users", status_code=201)
def create_user(
    body: AdminCreateUser,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    """Admin creates a user directly. No email confirmation; user must change password on first login."""
    from argon2.low_level import Type, hash_secret_raw
    import base64
    from sqlalchemy.exc import IntegrityError

    kdf_salt = uuid.uuid4().hex + uuid.uuid4().hex
    argon2_hash = _ph.hash(body.password)
    # Derive the db_key so the user's DB can be bootstrapped on first login
    raw = hash_secret_raw(
        secret=body.password.encode(),
        salt=bytes.fromhex(kdf_salt),
        time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, type=Type.ID,
    )
    _ = base64.b64encode(raw).decode()  # validated but not needed here

    user = UserRow(
        id=str(uuid.uuid4()),
        email=body.email,
        argon2_hash=argon2_hash,
        kdf_salt=kdf_salt,
        is_admin=False,
        is_founding_admin=False,
        is_blocked=False,
        email_confirmed=True,
        force_password_change=True,
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Email already registered")
    return _user_dict(user)


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
    session.query(TokenUsageRow).filter(TokenUsageRow.user_id == user_id).delete()
    session.query(TokenGrantRow).filter(TokenGrantRow.user_id == user_id).delete()
    session.commit()

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
    storage_limit_bytes: Optional[int] = None


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
    if body.storage_limit_bytes is not None:
        user.storage_limit_bytes = body.storage_limit_bytes if body.storage_limit_bytes > 0 else None
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


# ── Site settings ──────────────────────────────────────────────────────────────

def _get_all_settings(session: Session) -> dict[str, str]:
    settings = dict(_DEFAULT_SETTINGS)
    for row in session.query(SiteSettingsRow).all():
        settings[row.key] = row.value or ""
    return settings


@router.get("/settings")
def get_settings(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    return _get_all_settings(session)


@router.put("/settings")
def update_settings(
    body: dict,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    allowed = set(_DEFAULT_SETTINGS.keys())
    for key, value in body.items():
        if key not in allowed:
            continue
        row = session.get(SiteSettingsRow, key)
        if row is None:
            session.add(SiteSettingsRow(key=key, value=str(value) if value else ""))
        else:
            row.value = str(value) if value else ""
    session.commit()
    return _get_all_settings(session)


@router.post("/settings/test-smtp")
def test_smtp(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    from verdikt.api.email import get_smtp_config, send_email
    cfg = get_smtp_config(session)
    if not cfg.get("host") or not cfg.get("from"):
        raise HTTPException(status_code=400, detail="SMTP is not configured. Set host and from address first.")
    sent = send_email(
        session,
        to=cfg["from"],
        subject="Verdikt SMTP test",
        body_html="<p>SMTP is working correctly.</p>",
        body_text="SMTP is working correctly.",
    )
    if not sent:
        raise HTTPException(status_code=502, detail="Failed to send test email. Check server logs for details.")
    return {"ok": True}


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
        "input_cost_usd_per_mtok": m.input_cost_usd_per_mtok,
        "output_cost_usd_per_mtok": m.output_cost_usd_per_mtok,
        "privacy": m.privacy,
        "synced_at": m.synced_at.isoformat() if m.synced_at else None,
    }


@router.post("/models/sync")
def sync_models(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> list[dict]:
    import ollama as _ollama
    config = get_config()
    key_row = session.get(SiteSettingsRow, "ollama.api_key")
    extra_headers = {"Authorization": f"Bearer {key_row.value}"} if (key_row and key_row.value) else {}
    client = _ollama.Client(host=config.inference.ollama_base_url, headers=extra_headers)
    try:
        response = client.list()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot reach Ollama: {exc}")

    now = datetime.now(timezone.utc)
    for model in response.models:
        name = model.model or model.name
        details = model.details
        context_length: int | None = None
        has_vision = False
        try:
            info = client.show(name)
            ml = getattr(info, "modelinfo", None) or {}
            for key, val in ml.items():
                if "context_length" in key and isinstance(val, int):
                    context_length = val
                    break
            caps = getattr(info, "capabilities", None) or []
            if "vision" in caps:
                has_vision = True
        except Exception:
            pass

        families: list[str] = []
        if details:
            families = [f.lower() for f in (getattr(details, "families", None) or [])]
        if "clip" in families:
            has_vision = True

        name_lower = name.lower()
        if "embed" in name_lower:
            auto_type, auto_domain = "embedding", "text"
        elif has_vision:
            auto_type, auto_domain = "llm", "any"
        else:
            auto_type, auto_domain = "llm", "text"

        existing = session.get(ModelCatalogRow, name)
        if existing is None:
            session.add(ModelCatalogRow(
                id=name, source="ollama", type=auto_type, domain=auto_domain, enabled=False,
                display_name=name, description="[vision]" if has_vision else "",
                parameter_size=getattr(details, "parameter_size", None) if details else None,
                context_length=context_length, size_bytes=model.size,
                quantization=getattr(details, "quantization_level", None) if details else None,
                synced_at=now,
            ))
        else:
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
        id=body.id, source=body.source, type=body.type, domain=body.domain,
        enabled=False, display_name=body.display_name, description=body.description,
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
            row.is_default = False
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
            overlapping = [effective_domain, "any"] if effective_domain != "any" else ["any"]
            session.query(ModelCatalogRow).filter(
                ModelCatalogRow.type == effective_type,
                ModelCatalogRow.domain.in_(overlapping),
                ModelCatalogRow.id != row.id,
            ).update({"is_default": False})
        row.is_default = body.is_default
    session.commit()
    return _model_dict(row)


# ── Ollama auth (optional) ────────────────────────────────────────────────────

class OllamaKeyUpdate(BaseModel):
    api_key: str


@router.put("/ollama/key")
def set_ollama_key(
    body: OllamaKeyUpdate,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(SiteSettingsRow, "ollama.api_key")
    if row is None:
        session.add(SiteSettingsRow(key="ollama.api_key", value=body.api_key))
    else:
        row.value = body.api_key
    session.commit()
    return {"ok": True}


@router.delete("/ollama/key")
def delete_ollama_key(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(SiteSettingsRow, "ollama.api_key")
    if row is not None:
        session.delete(row)
        session.commit()
    return {"ok": True}


@router.get("/ollama/status")
def get_ollama_status(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(SiteSettingsRow, "ollama.api_key")
    return {"configured": bool(row and row.value)}


# ── Venice ────────────────────────────────────────────────────────────────────

class VeniceKeyUpdate(BaseModel):
    api_key: str


@router.put("/venice/key")
def set_venice_key(
    body: VeniceKeyUpdate,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(SiteSettingsRow, "venice.api_key")
    if row is None:
        session.add(SiteSettingsRow(key="venice.api_key", value=body.api_key))
    else:
        row.value = body.api_key
    session.commit()
    return {"ok": True}


@router.delete("/venice/key")
def delete_venice_key(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(SiteSettingsRow, "venice.api_key")
    if row is not None:
        session.delete(row)
        session.commit()
    return {"ok": True}


@router.get("/venice/status")
def get_venice_status(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(SiteSettingsRow, "venice.api_key")
    configured = bool(row and row.value)
    count = session.query(ModelCatalogRow).filter(ModelCatalogRow.source == "venice").count()
    return {"configured": configured, "model_count": count}


def _sync_venice_catalog(api_key: str, session) -> None:
    """Fetch the Venice model list and upsert into the local catalog. Shared by admin and personal-key sync."""
    import httpx as _httpx

    try:
        resp = _httpx.get(
            "https://api.venice.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot reach Venice API: {exc}")

    models_data = resp.json().get("data", [])
    now = datetime.now(timezone.utc)
    seen_ids: set[str] = set()

    for model in models_data:
        model_id = model.get("id", "")
        if not model_id:
            continue
        model_type_raw = str(model.get("type", "")).lower()
        if model_type_raw == "image":
            continue
        seen_ids.add(model_id)

        spec = model.get("model_spec") or {}
        capabilities = spec.get("capabilities") or {}
        pricing = spec.get("pricing") or {}

        name_lower = model_id.lower()
        if "embed" in name_lower or model_type_raw == "embedding":
            catalog_type, domain = "embedding", "text"
        else:
            catalog_type = "llm"
            supports_vision = capabilities.get("supportsVision", False)
            domain = "any" if (supports_vision or "vision" in name_lower) else "text"

        display_name = spec.get("name") or model_id
        description = spec.get("description") or ""
        context_length = model.get("context_length") or spec.get("availableContextTokens")
        quantization = capabilities.get("quantization") or None
        input_spec = pricing.get("input")
        output_spec = pricing.get("output")
        input_cost = input_spec.get("usd") if isinstance(input_spec, dict) else None
        output_cost = output_spec.get("usd") if isinstance(output_spec, dict) else None
        privacy = spec.get("privacy") or None

        existing = session.get(ModelCatalogRow, model_id)
        if existing is None:
            session.add(ModelCatalogRow(
                id=model_id, source="venice", type=catalog_type, domain=domain,
                enabled=False, display_name=display_name, description=description,
                context_length=context_length, quantization=quantization,
                input_cost_usd_per_mtok=input_cost, output_cost_usd_per_mtok=output_cost,
                privacy=privacy, synced_at=now,
            ))
        else:
            existing.synced_at = now
            existing.display_name = display_name
            existing.description = description
            existing.context_length = context_length
            existing.quantization = quantization
            existing.input_cost_usd_per_mtok = input_cost
            existing.output_cost_usd_per_mtok = output_cost
            existing.privacy = privacy
            existing.domain = domain

    if seen_ids:
        stale = session.query(ModelCatalogRow).filter(
            ModelCatalogRow.source == "venice",
            ModelCatalogRow.id.notin_(seen_ids),
        ).all()
        for m in stale:
            m.enabled = False

    session.commit()


@router.post("/models/sync-venice")
def sync_venice_models(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> list[dict]:
    row = session.get(SiteSettingsRow, "venice.api_key")
    if not row or not row.value:
        raise HTTPException(status_code=422, detail="Venice API key not configured. Set it first.")
    _sync_venice_catalog(row.value, session)
    rows = session.query(ModelCatalogRow).order_by(ModelCatalogRow.type, ModelCatalogRow.id).all()
    return [_model_dict(r) for r in rows]


# ── OpenRouter ────────────────────────────────────────────────────────────────

class OpenRouterKeyUpdate(BaseModel):
    api_key: str


@router.put("/openrouter/key")
def set_openrouter_key(
    body: OpenRouterKeyUpdate,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(SiteSettingsRow, "openrouter.api_key")
    if row is None:
        session.add(SiteSettingsRow(key="openrouter.api_key", value=body.api_key))
    else:
        row.value = body.api_key
    session.commit()
    return {"ok": True}


@router.delete("/openrouter/key")
def delete_openrouter_key(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(SiteSettingsRow, "openrouter.api_key")
    if row is not None:
        session.delete(row)
        session.commit()
    return {"ok": True}


@router.get("/openrouter/status")
def get_openrouter_status(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    row = session.get(SiteSettingsRow, "openrouter.api_key")
    configured = bool(row and row.value)
    count = session.query(ModelCatalogRow).filter(ModelCatalogRow.source == "openrouter").count()
    return {"configured": configured, "model_count": count}


def _sync_openrouter_catalog(api_key: str, session) -> None:
    """Fetch the OpenRouter model list and upsert into the local catalog. Shared by admin and personal-key sync."""
    import httpx as _httpx

    try:
        resp = _httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot reach OpenRouter API: {exc}")

    models_data = resp.json().get("data", [])
    now = datetime.now(timezone.utc)
    seen_ids: set[str] = set()

    for model in models_data:
        model_id = model.get("id", "")
        if not model_id:
            continue

        name_lower = model_id.lower()
        if "embed" in name_lower:
            continue

        seen_ids.add(model_id)

        display_name = model.get("name") or model_id
        context_length = model.get("context_length") or None
        pricing = model.get("pricing") or {}

        try:
            input_cost = float(pricing.get("prompt", 0) or 0) * 1_000_000
        except (TypeError, ValueError):
            input_cost = None
        try:
            output_cost = float(pricing.get("completion", 0) or 0) * 1_000_000
        except (TypeError, ValueError):
            output_cost = None

        architecture = model.get("architecture") or {}
        modality = str(architecture.get("modality") or "text->text")
        supports_image_input = "image" in modality.split("->")[0]
        domain = "any" if supports_image_input else "text"

        existing = session.get(ModelCatalogRow, model_id)
        if existing is None:
            session.add(ModelCatalogRow(
                id=model_id, source="openrouter", type="llm", domain=domain,
                enabled=False, display_name=display_name, description="",
                context_length=context_length,
                input_cost_usd_per_mtok=input_cost, output_cost_usd_per_mtok=output_cost,
                synced_at=now,
            ))
        else:
            existing.synced_at = now
            existing.display_name = display_name
            existing.context_length = context_length
            existing.input_cost_usd_per_mtok = input_cost
            existing.output_cost_usd_per_mtok = output_cost
            existing.domain = domain

    if seen_ids:
        stale = session.query(ModelCatalogRow).filter(
            ModelCatalogRow.source == "openrouter",
            ModelCatalogRow.id.notin_(seen_ids),
        ).all()
        for m in stale:
            m.enabled = False

    session.commit()


@router.post("/models/sync-openrouter")
def sync_openrouter_models(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> list[dict]:
    row = session.get(SiteSettingsRow, "openrouter.api_key")
    if not row or not row.value:
        raise HTTPException(status_code=422, detail="OpenRouter API key not configured. Set it first.")
    _sync_openrouter_catalog(row.value, session)
    rows = session.query(ModelCatalogRow).order_by(ModelCatalogRow.type, ModelCatalogRow.id).all()
    return [_model_dict(r) for r in rows]
