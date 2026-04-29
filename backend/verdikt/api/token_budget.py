from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from verdikt.storage.auth_orm import SiteSettingsRow, TokenGrantRow, TokenUsageRow, UserRow


def _get_effective_daily_grant(user: UserRow, session: Session) -> int | None:
    """Return the daily token grant for a user, falling back to site default. None = unlimited."""
    if user.daily_token_grant is not None:
        return user.daily_token_grant
    row = session.get(SiteSettingsRow, "default_daily_token_grant")
    if row and row.value:
        try:
            return int(row.value)
        except ValueError:
            pass
    return None  # unlimited


def _get_effective_expiry_days(user: UserRow, session: Session) -> int:
    expiry = getattr(user, "token_grant_expiry_days", None) or 7
    if expiry:
        return expiry
    row = session.get(SiteSettingsRow, "default_token_grant_expiry_days")
    if row and row.value:
        try:
            return int(row.value)
        except ValueError:
            pass
    return 7


def ensure_daily_grant(user_id: str, session: Session) -> None:
    """Lazily issue today's system daily grant if not yet issued today."""
    user = session.get(UserRow, user_id)
    if user is None:
        return
    effective_grant = _get_effective_daily_grant(user, session)
    if effective_grant is None:
        return  # unlimited

    today = date.today()
    existing = (
        session.query(TokenGrantRow)
        .filter(
            TokenGrantRow.user_id == user_id,
            TokenGrantRow.granted_by == "system_daily",
        )
        .order_by(TokenGrantRow.granted_at.desc())
        .first()
    )
    if existing is not None and existing.granted_at.date() == today:
        return  # already issued today

    from datetime import timedelta
    expiry_days = _get_effective_expiry_days(user, session)
    now = datetime.now(timezone.utc)
    session.add(TokenGrantRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        amount=effective_grant,
        granted_at=now,
        expires_at=now + timedelta(days=expiry_days),
        granted_by="system_daily",
        note=None,
    ))
    session.commit()


def get_token_balance(user_id: str, session: Session) -> Optional[int]:
    """Return remaining token balance, or None if the user has no grant limit (unlimited)."""
    user = session.get(UserRow, user_id)
    if user is None:
        return None
    effective_grant = _get_effective_daily_grant(user, session)
    if effective_grant is None:
        return None  # unlimited

    ensure_daily_grant(user_id, session)

    now = datetime.now(timezone.utc)
    granted = session.query(func.sum(TokenGrantRow.amount)).filter(
        TokenGrantRow.user_id == user_id,
        or_(TokenGrantRow.expires_at.is_(None), TokenGrantRow.expires_at > now),
    ).scalar() or 0

    used = session.query(
        func.sum(TokenUsageRow.prompt_tokens + TokenUsageRow.completion_tokens)
    ).filter(TokenUsageRow.user_id == user_id).scalar() or 0

    return max(0, int(granted) - int(used))


def check_token_budget(user_id: str, session: Session) -> None:
    """Raise HTTP 402 if the user's token balance is exhausted."""
    balance = get_token_balance(user_id, session)
    if balance is not None and balance <= 0:
        raise HTTPException(
            status_code=402,
            detail="Token budget exhausted. Contact your admin for more tokens.",
        )


def record_usage(
    user_id: str,
    project_id: Optional[str],
    model_id: str,
    source: str,
    prompt_tokens: int,
    completion_tokens: int,
    session: Session,
) -> None:
    """Insert a TokenUsageRow for a completed LLM call."""
    session.add(TokenUsageRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        project_id=project_id,
        model_id=model_id,
        source=source,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        recorded_at=datetime.now(timezone.utc),
    ))
    session.commit()
