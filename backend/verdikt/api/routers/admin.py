from __future__ import annotations

import shutil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_config, require_admin
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import UserRow

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
