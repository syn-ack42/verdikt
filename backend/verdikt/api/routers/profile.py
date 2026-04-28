from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from typing import Annotated

from verdikt.api.deps import get_auth_session, get_config, get_current_user, get_session
from verdikt.api.token_budget import check_token_budget, record_usage
from verdikt.core.user_models import AuthenticatedUser
from verdikt.core.models import DimensionProfile, PreferenceProfile
from verdikt.inference.crystalliser import ProfileCrystalliser
from verdikt.inference.resolver import resolve_llm_model
from verdikt.storage.sqlite import (
    SQLiteChunkStore, SQLiteProfileStore, SQLiteProjectStore, SQLiteRatingStore,
)

router = APIRouter(prefix="/api/projects/{project_id}/profile", tags=["profile"])

# In-memory set of project_ids currently crystallising (single-process only)
_crystallise_running: set[str] = set()


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


def _profile_response(p: PreferenceProfile) -> dict:
    profile_confidence = (
        round(p.score_sum / p.confirmed_count, 4) if p.confirmed_count > 0 else None
    )
    return {
        "id": p.id,
        "project_id": p.project_id,
        "version": p.version,
        "dimensions": [d.model_dump() for d in p.dimensions],
        "overall_summary": p.overall_summary,
        "rating_count": p.rating_count,
        "confirmed_count": p.confirmed_count,
        "score_sum": p.score_sum,
        "profile_confidence": profile_confidence,
        "created_at": p.created_at.isoformat(),
    }


@router.get("")
def get_profile(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    profile = SQLiteProfileStore(session).get_latest(project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No profile found")
    return _profile_response(profile)


@router.get("/versions")
def list_profile_versions(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[dict]:
    _get_project_or_404(project_id, session)
    return [_profile_response(p) for p in SQLiteProfileStore(session).list_versions(project_id)]


@router.get("/crystallise/status")
def crystallise_status(
    project_id: str,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict:
    return {"running": project_id in _crystallise_running}


@router.post("/crystallise", status_code=201)
def crystallise_profile(
    project_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> dict:
    check_token_budget(user.id, auth_session)
    proj = _get_project_or_404(project_id, session)
    rating_store = SQLiteRatingStore(session)
    chunk_store = SQLiteChunkStore(session)
    profile_store = SQLiteProfileStore(session)

    ratings = rating_store.list_by_project(project_id)
    non_skipped = [r for r in ratings if not r.skipped]

    if len(non_skipped) < proj.crystallisation_threshold:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Need {proj.crystallisation_threshold} ratings to crystallise, "
                f"have {len(non_skipped)}."
            ),
        )

    chunks_by_id = {c.id: c for c in chunk_store.list_by_project(project_id)}
    current = profile_store.get_latest(project_id)
    current_version = current.version if current else 0

    config = get_config()
    ollama_base_url, llm_model = resolve_llm_model(proj, config)
    crystalliser = ProfileCrystalliser(
        ollama_base_url=ollama_base_url,
        model=llm_model,
    )
    _crystallise_running.add(project_id)
    try:
        profile, prompt_tokens, completion_tokens = crystalliser.crystallise(
            project=proj,
            ratings=ratings,
            chunks_by_id=chunks_by_id,
            current_version=current_version,
        )
    except Exception as exc:
        import httpx as _httpx
        if isinstance(exc, _httpx.ConnectError):
            raise HTTPException(
                status_code=503,
                detail=f"Cannot reach Ollama at {config.inference.ollama_base_url}. Is it running?",
            )
        if isinstance(exc, _httpx.HTTPStatusError):
            raise HTTPException(status_code=502, detail=f"Ollama error: {exc.response.text[:200]}")
        raise HTTPException(status_code=500, detail=f"Crystallisation failed: {exc}")
    finally:
        _crystallise_running.discard(project_id)

    record_usage(user.id, project_id, llm_model, "crystallise", prompt_tokens, completion_tokens, auth_session)
    profile_store.save(profile)
    session.commit()
    return _profile_response(profile)


class ProfileUpdate(BaseModel):
    overall_summary: str | None = None
    dimensions: list[dict] | None = None


@router.put("")
def update_profile(
    project_id: str,
    body: ProfileUpdate,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    profile_store = SQLiteProfileStore(session)
    current = profile_store.get_latest(project_id)
    if current is None:
        raise HTTPException(status_code=404, detail="No profile found")

    new_profile = PreferenceProfile(
        id=str(uuid4()),
        project_id=project_id,
        version=current.version + 1,
        dimensions=[DimensionProfile(**d) for d in body.dimensions] if body.dimensions is not None else current.dimensions,
        overall_summary=body.overall_summary if body.overall_summary is not None else current.overall_summary,
        rating_count=current.rating_count,
        created_at=datetime.now(timezone.utc),
    )
    profile_store.save(new_profile)
    session.commit()
    return _profile_response(new_profile)


@router.post("/versions/{version_id}/restore", status_code=201)
def restore_profile_version(
    project_id: str,
    version_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    profile_store = SQLiteProfileStore(session)

    versions = profile_store.list_versions(project_id)
    target = next((v for v in versions if v.id == version_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Version not found")

    current = profile_store.get_latest(project_id)
    new_version = (current.version if current else 0) + 1

    restored = PreferenceProfile(
        id=str(uuid4()),
        project_id=project_id,
        version=new_version,
        dimensions=target.dimensions,
        overall_summary=target.overall_summary,
        rating_count=target.rating_count,
        created_at=datetime.now(timezone.utc),
    )
    profile_store.save(restored)
    session.commit()
    return _profile_response(restored)
