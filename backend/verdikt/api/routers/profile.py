from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_config, get_session
from verdikt.core.models import PreferenceProfile
from verdikt.inference.crystalliser import ProfileCrystalliser
from verdikt.storage.sqlite import (
    SQLiteChunkStore, SQLiteProfileStore, SQLiteProjectStore, SQLiteRatingStore,
)

router = APIRouter(prefix="/api/projects/{project_id}/profile", tags=["profile"])


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


def _profile_response(p: PreferenceProfile) -> dict:
    return {
        "id": p.id,
        "project_id": p.project_id,
        "version": p.version,
        "dimensions": [d.model_dump() for d in p.dimensions],
        "overall_summary": p.overall_summary,
        "rating_count": p.rating_count,
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


@router.post("/crystallise", status_code=201)
def crystallise_profile(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
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
    crystalliser = ProfileCrystalliser(
        ollama_base_url=config.inference.ollama_base_url,
        model=config.inference.ollama_model,
    )
    try:
        profile = crystalliser.crystallise(
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
    profile = profile_store.get_latest(project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No profile found")

    from verdikt.core.models import DimensionProfile
    if body.dimensions is not None:
        profile.dimensions = [DimensionProfile(**d) for d in body.dimensions]
    if body.overall_summary is not None:
        profile.overall_summary = body.overall_summary

    profile_store.update(profile)
    session.commit()
    return _profile_response(profile)
