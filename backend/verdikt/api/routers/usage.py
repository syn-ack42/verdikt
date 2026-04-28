from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_config, get_current_user, require_admin
from verdikt.api.token_budget import get_token_balance
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import TokenUsageRow, UserRow

router = APIRouter(prefix="/api", tags=["usage"])


def _usage_summary(user_id: str, session: Session) -> dict:
    now = datetime.now(timezone.utc)

    def _window(since: datetime | None) -> dict:
        q = session.query(
            func.sum(TokenUsageRow.prompt_tokens),
            func.sum(TokenUsageRow.completion_tokens),
        ).filter(TokenUsageRow.user_id == user_id)
        if since:
            q = q.filter(TokenUsageRow.recorded_at >= since)
        row = q.one()
        prompt = int(row[0] or 0)
        completion = int(row[1] or 0)
        return {"prompt": prompt, "completion": completion, "total": prompt + completion}

    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week = start_of_today - timedelta(days=now.weekday())
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Per-project breakdown (all time)
    rows = session.query(
        TokenUsageRow.project_id,
        func.sum(TokenUsageRow.prompt_tokens),
        func.sum(TokenUsageRow.completion_tokens),
    ).filter(
        TokenUsageRow.user_id == user_id,
        TokenUsageRow.project_id.isnot(None),
    ).group_by(TokenUsageRow.project_id).all()

    by_project = [
        {
            "project_id": r[0],
            "all_time": {
                "prompt": int(r[1] or 0),
                "completion": int(r[2] or 0),
                "total": int((r[1] or 0) + (r[2] or 0)),
            },
        }
        for r in rows
    ]

    balance = get_token_balance(user_id, session)
    return {
        "balance": balance,
        "today": _window(start_of_today),
        "week": _window(start_of_week),
        "month": _window(start_of_month),
        "all_time": _window(None),
        "by_project": by_project,
    }


@router.get("/usage")
def get_my_usage(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    return _usage_summary(user.id, session)


@router.get("/admin/users/{user_id}/usage")
def get_user_usage(
    user_id: str,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    if session.get(UserRow, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _usage_summary(user_id, session)
