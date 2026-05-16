from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from argon2 import PasswordHasher
from argon2.low_level import Type, hash_secret_raw
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from jose import jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_config, get_current_user, rekey_user_db
from verdikt.api.email import is_smtp_configured, send_email
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import EmailConfirmationRow, UserRow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

_ph = PasswordHasher()
_KDF_TIME_COST = 2
_KDF_MEMORY_COST = 65536  # 64 MiB
_KDF_PARALLELISM = 2
_KDF_HASH_LEN = 32
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_SECONDS = 30 * 24 * 3600
_CONFIRM_TOKEN_TTL_HOURS = 48


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ConfirmEmailRequest(BaseModel):
    token: str


def _check_password_strength(password: str) -> None:
    """Raise HTTP 400 if the password is too weak (zxcvbn score < 3)."""
    try:
        from zxcvbn import zxcvbn
        result = zxcvbn(password)
        if result["score"] < 3:
            feedback = result.get("feedback", {})
            warning = feedback.get("warning") or "Choose a longer or more unique password — a passphrase works well."
            suggestions = feedback.get("suggestions", [])
            detail = warning
            if suggestions:
                detail += " " + suggestions[0]
            raise HTTPException(status_code=400, detail=detail)
    except ImportError:
        # zxcvbn not installed — fall back to length check
        if len(password) < 10:
            raise HTTPException(status_code=400, detail="Password must be at least 10 characters")


def _derive_key(password: str, kdf_salt_hex: str) -> str:
    """Derive a 32-byte encryption key from password + salt; return as base64."""
    raw = hash_secret_raw(
        secret=password.encode(),
        salt=bytes.fromhex(kdf_salt_hex),
        time_cost=_KDF_TIME_COST,
        memory_cost=_KDF_MEMORY_COST,
        parallelism=_KDF_PARALLELISM,
        hash_len=_KDF_HASH_LEN,
        type=Type.ID,
    )
    return base64.b64encode(raw).decode()


def _make_token(user: UserRow, db_key: str) -> str:
    config = get_config()
    payload = {
        "sub": user.id,
        "email": user.email,
        "admin": user.is_admin,
        "key": db_key,
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=_JWT_ALGORITHM)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "verdikt_token",
        token,
        max_age=_JWT_EXPIRE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
    )


def _user_response(user: UserRow) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "is_admin": user.is_admin,
        "is_founding_admin": getattr(user, "is_founding_admin", False),
        "force_password_change": getattr(user, "force_password_change", False),
        "email_confirmed": getattr(user, "email_confirmed", True),
    }


@router.post("/register")
def register(
    body: RegisterRequest,
    response: Response,
    session: Annotated[Session, Depends(get_auth_session)],
):
    _check_password_strength(body.password)

    is_first = session.query(UserRow).count() == 0
    smtp_ready = is_smtp_configured(session)
    # Founding admin and instances without SMTP skip email confirmation
    needs_confirmation = smtp_ready and not is_first

    kdf_salt = uuid.uuid4().hex + uuid.uuid4().hex
    argon2_hash = _ph.hash(body.password)
    db_key = _derive_key(body.password, kdf_salt)

    user = UserRow(
        id=str(uuid.uuid4()),
        email=body.email,
        argon2_hash=argon2_hash,
        kdf_salt=kdf_salt,
        is_admin=is_first,
        is_founding_admin=is_first,
        is_blocked=False,
        email_confirmed=not needs_confirmation,
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Email already registered")

    if needs_confirmation:
        _send_confirmation_email(user, session)
        return {"pending_confirmation": True, "email": user.email}

    token = _make_token(user, db_key)
    _set_cookie(response, token)
    return _user_response(user)


def _send_confirmation_email(user: UserRow, session: Session) -> None:
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    session.add(EmailConfirmationRow(
        token=token,
        user_id=user.id,
        expires_at=now + timedelta(hours=_CONFIRM_TOKEN_TTL_HOURS),
        created_at=now,
    ))
    session.commit()

    config = get_config()
    confirm_url = f"{config.app_base_url}/confirm-email?token={token}"
    send_email(
        session,
        to=user.email,
        subject="Confirm your Verdikt account",
        body_html=f"""
<p>Thanks for registering with Verdikt.</p>
<p>Please click the link below to confirm your email address and activate your account.
The link expires in {_CONFIRM_TOKEN_TTL_HOURS} hours.</p>
<p><a href="{confirm_url}">{confirm_url}</a></p>
<p>If you did not create this account, you can ignore this email.</p>
""",
        body_text=(
            f"Confirm your Verdikt account by visiting:\n{confirm_url}\n\n"
            f"The link expires in {_CONFIRM_TOKEN_TTL_HOURS} hours."
        ),
    )


@router.post("/confirm-email")
def confirm_email(
    body: ConfirmEmailRequest,
    session: Annotated[Session, Depends(get_auth_session)],
):
    row = session.get(EmailConfirmationRow, body.token)
    if row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired confirmation link")
    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        session.delete(row)
        session.commit()
        raise HTTPException(status_code=400, detail="Confirmation link has expired. Please register again.")

    user = session.get(UserRow, row.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Account no longer exists")

    user.email_confirmed = True
    session.delete(row)
    session.commit()
    return {"ok": True, "email": user.email}


class ResendConfirmationRequest(BaseModel):
    email: EmailStr


_RESEND_COOLDOWN_SECONDS = 60


@router.post("/resend-confirmation")
def resend_confirmation(
    body: ResendConfirmationRequest,
    session: Annotated[Session, Depends(get_auth_session)],
):
    # Always return ok to avoid email enumeration
    user = session.query(UserRow).filter_by(email=body.email).first()
    if user is None or getattr(user, "email_confirmed", True):
        return {"ok": True}

    # Rate-limit: skip if a token was created within the cooldown window
    recent = (
        session.query(EmailConfirmationRow)
        .filter_by(user_id=user.id)
        .order_by(EmailConfirmationRow.created_at.desc())
        .first()
    )
    if recent is not None:
        age = (datetime.now(timezone.utc) - recent.created_at.replace(tzinfo=timezone.utc)).total_seconds()
        if age < _RESEND_COOLDOWN_SECONDS:
            return {"ok": True}
        session.delete(recent)

    _send_confirmation_email(user, session)
    return {"ok": True}


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    session: Annotated[Session, Depends(get_auth_session)],
):
    user = session.query(UserRow).filter_by(email=body.email).first()
    if user is None or user.argon2_hash is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    try:
        _ph.verify(user.argon2_hash, body.password)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Account blocked")
    if not getattr(user, "email_confirmed", True):
        raise HTTPException(status_code=403, detail="Email address not confirmed. Check your inbox.")

    db_key = _derive_key(body.password, user.kdf_salt)
    token = _make_token(user, db_key)
    _set_cookie(response, token)
    return _user_response(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("verdikt_token")
    return {"ok": True}


@router.get("/me")
def me(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    row = session.get(UserRow, user.id)
    return {
        "id": user.id,
        "email": user.email,
        "is_admin": user.is_admin,
        "is_founding_admin": getattr(row, "is_founding_admin", False) if row else False,
        "force_password_change": getattr(row, "force_password_change", False) if row else False,
        "email_confirmed": getattr(row, "email_confirmed", True) if row else True,
        "storage_limit_bytes": getattr(row, "storage_limit_bytes", None) if row else None,
    }


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    row = session.get(UserRow, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    if row.argon2_hash is None:
        raise HTTPException(status_code=400, detail="OAuth accounts cannot change password here")

    try:
        _ph.verify(row.argon2_hash, body.old_password)
    except Exception:
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    _check_password_strength(body.new_password)

    new_salt = uuid.uuid4().hex + uuid.uuid4().hex
    new_db_key = _derive_key(body.new_password, new_salt)

    # Re-encrypt the user's SQLCipher DB with the new key
    rekey_user_db(user.id, user.db_key, new_db_key)

    row.argon2_hash = _ph.hash(body.new_password)
    row.kdf_salt = new_salt
    row.force_password_change = False
    session.commit()

    token = _make_token(row, new_db_key)
    _set_cookie(response, token)
    return {"ok": True}


# ── Per-user Venice API key ──────────────────────────────────────────────────

def _encrypt_user_venice_key(raw_key: str, jwt_secret: str) -> str:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    wrap_key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b"verdikt-user-venice-key-wrap-v1",
    ).derive(jwt_secret.encode())
    return Fernet(base64.urlsafe_b64encode(wrap_key)).encrypt(raw_key.encode()).decode()


class SetVeniceKeyRequest(BaseModel):
    api_key: str


@router.put("/me/venice-key")
def set_venice_key(
    body: SetVeniceKeyRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    if not body.api_key.strip():
        raise HTTPException(status_code=400, detail="api_key must not be empty")
    config = get_config()
    row = session.get(UserRow, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    row.venice_api_key_enc = _encrypt_user_venice_key(body.api_key.strip(), config.jwt_secret)
    session.commit()
    return {"ok": True}


@router.delete("/me/venice-key")
def delete_venice_key(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    row = session.get(UserRow, user.id)
    if row is not None:
        row.venice_api_key_enc = None
        session.commit()
    return {"ok": True}


@router.get("/me/venice-key/status")
def venice_key_status(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_auth_session)],
):
    row = session.get(UserRow, user.id)
    configured = bool(row and getattr(row, "venice_api_key_enc", None))
    return {"configured": configured}



# ── OAuth ─────────────────────────────────────────────────────────────────────

_OAUTH_PROVIDERS = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "user:email",
    },
}


def _wrap_oauth_db_key(db_key_bytes: bytes, jwt_secret: str) -> str:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    wrap_key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b"verdikt-oauth-key-wrap-v1",
    ).derive(jwt_secret.encode())
    return Fernet(base64.urlsafe_b64encode(wrap_key)).encrypt(db_key_bytes).decode()


def _unwrap_oauth_db_key(ciphertext: str, jwt_secret: str) -> str:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    wrap_key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b"verdikt-oauth-key-wrap-v1",
    ).derive(jwt_secret.encode())
    raw = Fernet(base64.urlsafe_b64encode(wrap_key)).decrypt(ciphertext.encode())
    return base64.b64encode(raw).decode()


def _make_oauth_state(jwt_secret: str) -> str:
    nonce = os.urandom(16).hex()
    expiry = str(int(time.time()) + 600)
    sig = hmac.new(jwt_secret.encode(), f"{nonce}.{expiry}".encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{expiry}.{sig}"


def _verify_oauth_state(state: str, jwt_secret: str) -> bool:
    try:
        nonce, expiry, sig = state.split(".")
    except ValueError:
        return False
    expected = hmac.new(jwt_secret.encode(), f"{nonce}.{expiry}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    return int(expiry) > int(time.time())


def _find_or_create_oauth_user(
    provider: str, provider_id: str, email: str, session: Session, config,
) -> tuple[UserRow, str]:
    existing = session.query(UserRow).filter_by(
        oauth_provider=provider, oauth_provider_id=provider_id
    ).first()
    if existing:
        db_key = _unwrap_oauth_db_key(existing.oauth_db_key_enc, config.jwt_secret)
        return existing, db_key

    by_email = session.query(UserRow).filter_by(email=email).first()
    if by_email:
        if not by_email.oauth_db_key_enc:
            raw_key = os.urandom(32)
            by_email.oauth_db_key_enc = _wrap_oauth_db_key(raw_key, config.jwt_secret)
        by_email.oauth_provider = provider
        by_email.oauth_provider_id = provider_id
        by_email.email_confirmed = True
        session.commit()
        db_key = _unwrap_oauth_db_key(by_email.oauth_db_key_enc, config.jwt_secret)
        return by_email, db_key

    is_first = session.query(UserRow).count() == 0
    raw_key = os.urandom(32)
    enc_key = _wrap_oauth_db_key(raw_key, config.jwt_secret)
    user = UserRow(
        id=str(uuid.uuid4()),
        email=email,
        argon2_hash=None,
        kdf_salt=None,
        is_admin=is_first,
        is_founding_admin=is_first,
        is_blocked=False,
        email_confirmed=True,
        created_at=datetime.now(timezone.utc),
        oauth_provider=provider,
        oauth_provider_id=provider_id,
        oauth_db_key_enc=enc_key,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    return user, base64.b64encode(raw_key).decode()


@router.get("/oauth/providers")
def list_oauth_providers() -> list[str]:
    config = get_config()
    providers = []
    if config.google_client_id and config.google_client_secret:
        providers.append("google")
    if config.github_client_id and config.github_client_secret:
        providers.append("github")
    return providers


@router.get("/oauth/{provider}/authorize")
def oauth_authorize(provider: str) -> RedirectResponse:
    if provider not in _OAUTH_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    config = get_config()
    client_id = getattr(config, f"{provider}_client_id", None)
    if not client_id:
        raise HTTPException(status_code=501, detail=f"Provider '{provider}' is not configured")

    p = _OAUTH_PROVIDERS[provider]
    state = _make_oauth_state(config.jwt_secret)
    redirect_uri = f"{config.oauth_redirect_base}/api/auth/oauth/{provider}/callback"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": p["scope"],
        "state": state,
    }
    if provider == "google":
        params["access_type"] = "online"

    from urllib.parse import urlencode
    return RedirectResponse(p["auth_url"] + "?" + urlencode(params))


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: Annotated[Session, Depends(get_auth_session)] = None,
) -> RedirectResponse:
    if provider not in _OAUTH_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown provider")
    config = get_config()

    if error:
        return RedirectResponse("/login?error=oauth_denied")
    if not state or not _verify_oauth_state(state, config.jwt_secret):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    client_id = getattr(config, f"{provider}_client_id", None)
    client_secret = getattr(config, f"{provider}_client_secret", None)
    if not client_id or not client_secret:
        raise HTTPException(status_code=501, detail="Provider not configured")

    p = _OAUTH_PROVIDERS[provider]
    redirect_uri = f"{config.oauth_redirect_base}/api/auth/oauth/{provider}/callback"

    token_resp = httpx.post(
        p["token_url"],
        data={
            "client_id": client_id, "client_secret": client_secret,
            "code": code, "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        },
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    if token_resp.status_code != 200:
        return RedirectResponse("/login?error=oauth_token_failed")

    access_token = token_resp.json().get("access_token")
    if not access_token:
        return RedirectResponse("/login?error=oauth_token_failed")

    user_resp = httpx.get(
        p["userinfo_url"],
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=10.0,
    )
    if user_resp.status_code != 200:
        return RedirectResponse("/login?error=oauth_userinfo_failed")

    user_info = user_resp.json()
    email: str | None = user_info.get("email")
    if not email and provider == "github":
        emails_resp = httpx.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10.0,
        )
        if emails_resp.status_code == 200:
            email = next(
                (e["email"] for e in emails_resp.json() if e.get("primary") and e.get("verified")),
                None,
            )

    if not email:
        return RedirectResponse("/login?error=oauth_no_email")

    provider_id: str = str(user_info.get("sub") or user_info.get("id") or "")
    if not provider_id:
        return RedirectResponse("/login?error=oauth_no_id")

    user, db_key = _find_or_create_oauth_user(provider, provider_id, email, session, config)
    if user.is_blocked:
        return RedirectResponse("/login?error=account_blocked")

    token = _make_token(user, db_key)
    resp = RedirectResponse("/")
    _set_cookie(resp, token)
    return resp
