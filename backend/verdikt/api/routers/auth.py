from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from argon2 import PasswordHasher
from argon2.low_level import Type, hash_secret_raw
from fastapi import APIRouter, Depends, HTTPException, Response
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
