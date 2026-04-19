from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_session
from verdikt.core.models import Domain, Project, RatingDimension
from verdikt.storage.sqlite import SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    domain: str = "text"
    rating_dimensions: list[dict] = []
    chunk_min_size: int = 600
    chunk_max_size: int = 800
    crystallisation_threshold: int = 50


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    rating_dimensions: list[dict] | None = None
    chunk_min_size: int | None = None
    chunk_max_size: int | None = None
    crystallisation_threshold: int | None = None


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
    )
    SQLiteProjectStore(session).create(proj)
    session.commit()
    return _project_response(proj)


@router.get("/{project_id}")
def get_project(project_id: str, session: Session = Depends(get_session)) -> dict:
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_response(proj)


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

    if values:
        session.execute(sql_update(ProjectRow).where(ProjectRow.id == project_id).values(**values))
        session.flush()
        session.commit()

    proj = store.get(project_id)
    return _project_response(proj)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, session: Session = Depends(get_session)) -> None:
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
    chroma = _chromadb.PersistentClient(path=str(config.chroma_path))
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
