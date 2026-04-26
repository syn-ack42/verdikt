from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from typing import Annotated

from verdikt.api.deps import get_current_user, get_session
from verdikt.core.user_models import AuthenticatedUser
from verdikt.core.models import Domain, Project, RatingDimension
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLiteProfileStore, SQLiteProjectStore, SQLiteRatingStore

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    domain: str = "text"
    rating_dimensions: list[dict] = []
    chunk_min_size: int = 600
    chunk_max_size: int = 800
    crystallisation_threshold: int = 50
    min_profile_confidence: float = 0.9
    llm_model: str | None = None
    embedding_model: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    rating_dimensions: list[dict] | None = None
    chunk_min_size: int | None = None
    chunk_max_size: int | None = None
    crystallisation_threshold: int | None = None
    min_profile_confidence: float | None = None
    llm_model: str | None = None
    embedding_model: str | None = None
    dimension_renames: dict[str, str] | None = None  # old_name -> new_name


def _project_response(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "domain": p.domain,
        "rating_dimensions": [d.model_dump() for d in p.rating_dimensions],
        "chunk_min_size": p.chunk_min_size,
        "chunk_max_size": p.chunk_max_size,
        "crystallisation_threshold": p.crystallisation_threshold,
        "min_profile_confidence": p.min_profile_confidence,
        "llm_model": p.llm_model,
        "embedding_model": p.embedding_model,
        "created_at": p.created_at.isoformat(),
    }


@router.get("")
def list_projects(session: Session = Depends(get_session)) -> list[dict]:
    return [_project_response(p) for p in SQLiteProjectStore(session).list_all()]


@router.post("", status_code=201)
def create_project(
    body: ProjectCreate,
    session: Session = Depends(get_session),
) -> dict:
    dims = [RatingDimension(**d) for d in body.rating_dimensions]
    proj = Project(
        name=body.name,
        description=body.description,
        domain=Domain(body.domain),
        rating_dimensions=dims,
        chunk_min_size=body.chunk_min_size,
        chunk_max_size=body.chunk_max_size,
        crystallisation_threshold=body.crystallisation_threshold,
        min_profile_confidence=body.min_profile_confidence,
        llm_model=body.llm_model,
        embedding_model=body.embedding_model,
    )
    SQLiteProjectStore(session).create(proj)
    session.commit()
    return _project_response(proj)


@router.get("/{project_id}")
def get_project(project_id: str, session: Session = Depends(get_session)) -> dict:
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rating_count = SQLiteRatingStore(session).count_by_project(project_id)
    confidence = min(1.0, rating_count / proj.crystallisation_threshold) if proj.crystallisation_threshold > 0 else 1.0
    profile = SQLiteProfileStore(session).get_latest(project_id)
    profile_confirmed_count = profile.confirmed_count if profile else 0
    profile_confidence = (
        round(profile.score_sum / profile.confirmed_count, 4)
        if profile and profile.confirmed_count > 0 else None
    )
    return {
        **_project_response(proj),
        "confidence": round(confidence, 3),
        "profile_confirmed_count": profile_confirmed_count,
        "profile_confidence": profile_confidence,
    }


@router.put("/{project_id}")
def update_project(
    project_id: str,
    body: ProjectUpdate,
    session: Session = Depends(get_session),
) -> dict:
    from sqlalchemy import update as sql_update
    from verdikt.storage.orm import ProjectRow
    import json

    store = SQLiteProjectStore(session)
    proj = store.get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")

    values: dict = {}
    if body.name is not None:
        values["name"] = body.name
    if body.description is not None:
        values["description"] = body.description
    if body.rating_dimensions is not None:
        values["rating_dimensions"] = json.dumps(body.rating_dimensions)
    if body.chunk_min_size is not None:
        values["chunk_min_size"] = body.chunk_min_size
    if body.chunk_max_size is not None:
        values["chunk_max_size"] = body.chunk_max_size
    if body.crystallisation_threshold is not None:
        values["crystallisation_threshold"] = body.crystallisation_threshold
    if body.min_profile_confidence is not None:
        values["min_profile_confidence"] = body.min_profile_confidence
    if body.llm_model is not None:
        values["llm_model"] = body.llm_model
    if body.embedding_model is not None:
        # Reject change if material has already been embedded — vectors would be incompatible
        from verdikt.core.models import PipelinePhase
        from verdikt.storage.orm import MaterialItemRow
        from sqlalchemy import select as _select
        embedded = session.execute(
            _select(MaterialItemRow.id).where(
                MaterialItemRow.project_id == project_id,
                MaterialItemRow.pipeline_phase.notin_([
                    PipelinePhase.INGESTED.value,
                    PipelinePhase.CHUNKED.value,
                ]),
            ).limit(1)
        ).scalar_one_or_none()
        if embedded is not None:
            raise HTTPException(
                status_code=409,
                detail="Embedding model cannot be changed after material has been embedded. Re-ingest to start fresh.",
            )
        values["embedding_model"] = body.embedding_model

    if values:
        session.execute(sql_update(ProjectRow).where(ProjectRow.id == project_id).values(**values))
        session.flush()

    if body.dimension_renames:
        from verdikt.storage.orm import RatingRow
        rows = session.query(RatingRow).filter(RatingRow.project_id == project_id).all()
        for row in rows:
            scores: dict = json.loads(row.dimension_scores)
            new_scores = {body.dimension_renames.get(k, k): v for k, v in scores.items()}
            if new_scores != scores:
                row.dimension_scores = json.dumps(new_scores)
        session.flush()

    session.commit()
    proj = store.get(project_id)
    return _project_response(proj)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
) -> None:
    import chromadb as _chromadb
    from verdikt.api.deps import get_config
    from verdikt.storage.chroma import ChromaVectorStore

    store = SQLiteProjectStore(session)
    proj = store.get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")

    config = get_config()
    mat_store = SQLiteMaterialStore(session)
    chunk_store = SQLiteChunkStore(session)
    items = mat_store.list_by_project(proj.id)
    chroma = _chromadb.PersistentClient(path=str(config.user_chroma_path(user.id)))
    vector_store = ChromaVectorStore(chroma, f"project_{proj.id}")

    for item in items:
        chunks = chunk_store.list_by_material(item.id)
        vector_store.delete_items([c.id for c in chunks])
        chunk_store.delete_by_material(item.id)
        mat_store.delete(item.id)

    try:
        vector_store.delete_collection()
    except Exception:
        pass

    store.delete(proj.id)
    session.commit()
