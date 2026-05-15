from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_config, get_current_user, get_session, require_admin
from verdikt.api.token_budget import get_token_balance
from verdikt.core.user_models import AuthenticatedUser
from verdikt.storage.auth_orm import ModelCatalogRow, TokenUsageRow, UserRow
from verdikt.storage.sqlite import SQLiteProjectStore

router = APIRouter(prefix="/api", tags=["usage"])


def _model_rates(session: Session) -> dict[str, tuple[float, float]]:
    """Return {model_id: (input_per_mtok, output_per_mtok)} for models with pricing."""
    rows = session.query(
        ModelCatalogRow.id,
        ModelCatalogRow.input_cost_usd_per_mtok,
        ModelCatalogRow.output_cost_usd_per_mtok,
    ).filter(ModelCatalogRow.input_cost_usd_per_mtok.isnot(None)).all()
    return {r[0]: (r[1] or 0.0, r[2] or 0.0) for r in rows}


def _compute_cost(prompt: int, completion: int, model_id: str, rates: dict) -> float | None:
    if model_id not in rates:
        return None
    in_rate, out_rate = rates[model_id]
    return (prompt * in_rate + completion * out_rate) / 1_000_000


def _usage_summary(user_id: str, session: Session, user_session: Session | None = None) -> dict:
    now = datetime.now(timezone.utc)
    rates = _model_rates(session)

    def _window(since: datetime | None) -> dict:
        q = session.query(
            TokenUsageRow.model_id,
            func.sum(TokenUsageRow.prompt_tokens),
            func.sum(TokenUsageRow.completion_tokens),
        ).filter(TokenUsageRow.user_id == user_id).group_by(TokenUsageRow.model_id)
        if since:
            q = q.filter(TokenUsageRow.recorded_at >= since)
        rows = q.all()
        prompt = sum(int(r[1] or 0) for r in rows)
        completion = sum(int(r[2] or 0) for r in rows)
        cost_usd: float | None = None
        for r in rows:
            c = _compute_cost(int(r[1] or 0), int(r[2] or 0), r[0], rates)
            if c is not None:
                cost_usd = (cost_usd or 0.0) + c
        result: dict = {"prompt": prompt, "completion": completion, "total": prompt + completion}
        if cost_usd is not None:
            result["cost_usd"] = round(cost_usd, 6)
        return result

    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_week = start_of_today - timedelta(days=now.weekday())
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Per-project breakdown (all time)
    proj_rows = session.query(
        TokenUsageRow.project_id,
        TokenUsageRow.model_id,
        func.sum(TokenUsageRow.prompt_tokens),
        func.sum(TokenUsageRow.completion_tokens),
    ).filter(
        TokenUsageRow.user_id == user_id,
        TokenUsageRow.project_id.isnot(None),
    ).group_by(TokenUsageRow.project_id, TokenUsageRow.model_id).all()

    project_names: dict[str, str] = {}
    if user_session is not None:
        store = SQLiteProjectStore(user_session)
        for proj in store.list_all():
            project_names[proj.id] = proj.name

    # Aggregate per project across models
    proj_agg: dict[str, dict] = {}
    for r in proj_rows:
        pid, mid, p, c = r[0], r[1], int(r[2] or 0), int(r[3] or 0)
        if pid not in proj_agg:
            proj_agg[pid] = {"prompt": 0, "completion": 0, "cost_usd": None}
        proj_agg[pid]["prompt"] += p
        proj_agg[pid]["completion"] += c
        cost = _compute_cost(p, c, mid, rates)
        if cost is not None:
            proj_agg[pid]["cost_usd"] = (proj_agg[pid]["cost_usd"] or 0.0) + cost

    by_project = []
    for pid, agg in proj_agg.items():
        entry: dict = {
            "project_id": pid,
            "project_name": project_names.get(pid),
            "all_time": {
                "prompt": agg["prompt"],
                "completion": agg["completion"],
                "total": agg["prompt"] + agg["completion"],
            },
        }
        if agg["cost_usd"] is not None:
            entry["all_time"]["cost_usd"] = round(agg["cost_usd"], 6)
        by_project.append(entry)

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
    user_session: Annotated[Session, Depends(get_session)],
) -> dict:
    return _usage_summary(user.id, session, user_session)


@router.get("/admin/users/{user_id}/usage")
def get_user_usage(
    user_id: str,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict:
    if session.get(UserRow, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _usage_summary(user_id, session)
