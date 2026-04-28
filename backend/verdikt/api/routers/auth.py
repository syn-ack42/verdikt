from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timezone
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

from verdikt.api.deps import get_auth_session, get_config, get_current_user
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import UserRow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

_ph = PasswordHasher()
_KDF_TIME_COST = 2
_KDF_MEMORY_COST = 65536  # 64 MiB
_KDF_PARALLELISM = 2
_KDF_HASH_LEN = 32
_JWT_ALGORITHM = "HS256"
# 30-day token — user stays logged in across restarts
_JWT_EXPIRE_SECONDS = 30 * 24 * 3600


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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
        secure=False,  # set to True behind HTTPS reverse proxy
    )


@router.post("/register")
def register(
    body: RegisterRequest,
    response: Response,
    session: Annotated[Session, Depends(get_auth_session)],
):
    # First user becomes admin
    is_first = session.query(UserRow).count() == 0

    kdf_salt = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars = 32 bytes
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
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Email already registered")

    token = _make_token(user, db_key)
    _set_cookie(response, token)
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    session: Annotated[Session, Depends(get_auth_session)],
):
    user = session.query(UserRow).filter_by(email=body.email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    try:
        _ph.verify(user.argon2_hash, body.password)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Account blocked")

    db_key = _derive_key(body.password, user.kdf_salt)
    token = _make_token(user, db_key)
    _set_cookie(response, token)
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("verdikt_token")
    return {"ok": True}


@router.get("/me")
def me(user: Annotated[AuthenticatedUser, Depends(get_current_user)]):
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


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
    """Encrypt a DB key for an OAuth user using Fernet with HKDF-derived wrap key."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    wrap_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"verdikt-oauth-key-wrap-v1",
    ).derive(jwt_secret.encode())
    fernet_key = base64.urlsafe_b64encode(wrap_key)
    return Fernet(fernet_key).encrypt(db_key_bytes).decode()


def _unwrap_oauth_db_key(ciphertext: str, jwt_secret: str) -> str:
    """Decrypt an OAuth user's DB key; returns base64-encoded key."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    wrap_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"verdikt-oauth-key-wrap-v1",
    ).derive(jwt_secret.encode())
    fernet_key = base64.urlsafe_b64encode(wrap_key)
    raw = Fernet(fernet_key).decrypt(ciphertext.encode())
    return base64.b64encode(raw).decode()


def _make_oauth_state(jwt_secret: str) -> str:
    nonce = os.urandom(16).hex()
    expiry = str(int(time.time()) + 600)  # 10-minute window
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
    provider: str,
    provider_id: str,
    email: str,
    session: Session,
    config,
) -> tuple[UserRow, str]:
    """Return (user, db_key_b64). Creates user if needed."""
    # 1. Look up by provider + provider_id
    existing = session.query(UserRow).filter_by(
        oauth_provider=provider, oauth_provider_id=provider_id
    ).first()
    if existing:
        db_key = _unwrap_oauth_db_key(existing.oauth_db_key_enc, config.jwt_secret)
        return existing, db_key

    # 2. Look up by email — link OAuth to existing account
    by_email = session.query(UserRow).filter_by(email=email).first()
    if by_email:
        if not by_email.oauth_db_key_enc:
            # First OAuth link for a password-auth user: derive DB key from stored credentials
            # We can't re-derive (no password), so generate a new independent key
            raw_key = os.urandom(32)
            by_email.oauth_db_key_enc = _wrap_oauth_db_key(raw_key, config.jwt_secret)
        by_email.oauth_provider = provider
        by_email.oauth_provider_id = provider_id
        session.commit()
        db_key = _unwrap_oauth_db_key(by_email.oauth_db_key_enc, config.jwt_secret)
        return by_email, db_key

    # 3. Create new user
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
    db_key_b64 = base64.b64encode(raw_key).decode()
    return user, db_key_b64


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
    url = p["auth_url"] + "?" + urlencode(params)
    return RedirectResponse(url)


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

    # Exchange code for access token
    headers = {"Accept": "application/json"}
    token_resp = httpx.post(
        p["token_url"],
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        headers=headers,
        timeout=15.0,
    )
    if token_resp.status_code != 200:
        return RedirectResponse("/login?error=oauth_token_failed")

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse("/login?error=oauth_token_failed")

    # Fetch user info
    user_resp = httpx.get(
        p["userinfo_url"],
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=10.0,
    )
    if user_resp.status_code != 200:
        return RedirectResponse("/login?error=oauth_userinfo_failed")

    user_info = user_resp.json()

    # Extract email
    email: str | None = user_info.get("email")
    if not email and provider == "github":
        # GitHub may not include email in /user; fetch separately
        emails_resp = httpx.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10.0,
        )
        if emails_resp.status_code == 200:
            primary = next(
                (e["email"] for e in emails_resp.json() if e.get("primary") and e.get("verified")),
                None,
            )
            email = primary

    if not email:
        return RedirectResponse("/login?error=oauth_no_email")

    provider_id: str = str(user_info.get("sub") or user_info.get("id") or "")
    if not provider_id:
        return RedirectResponse("/login?error=oauth_no_id")

    user, db_key = _find_or_create_oauth_user(provider, provider_id, email, session, config)

    if user.is_blocked:
        return RedirectResponse("/login?error=account_blocked")

    token = _make_token(user, db_key)
    response = RedirectResponse("/")
    _set_cookie(response, token)
    return response
