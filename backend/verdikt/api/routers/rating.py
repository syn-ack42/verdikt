from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_session
from verdikt.core.models import Rating
from verdikt.pipeline.selector import RatingSelector
from verdikt.storage.sqlite import (
    SQLiteChunkStore, SQLiteMaterialStore, SQLiteProjectStore, SQLiteRatingStore,
)

router = APIRouter(prefix="/api/projects/{project_id}/ratings", tags=["ratings"])


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


def _rating_response(r: Rating) -> dict:
    return {
        "id": r.id,
        "project_id": r.project_id,
        "chunk_id": r.chunk_id,
        "material_item_id": r.material_item_id,
        "dimension_scores": r.dimension_scores,
        "skipped": r.skipped,
        "skip_reason": r.skip_reason,
        "rated_at": r.rated_at.isoformat(),
    }


@router.get("/next")
def next_chunk(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    chunk_store = SQLiteChunkStore(session)
    rating_store = SQLiteRatingStore(session)
    mat_store = SQLiteMaterialStore(session)

    chunk = RatingSelector(chunk_store, rating_store).next_chunk(proj.id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="No unrated chunks available")

    material_item = mat_store.get(chunk.material_item_id)
    total_chunks = len(chunk_store.list_by_project(proj.id))
    total_rated = rating_store.count_by_project(proj.id)

    return {
        "chunk": {
            "id": chunk.id,
            "content": chunk.content if isinstance(chunk.content, str) else None,
            "position": chunk.position,
            "cluster_id": chunk.cluster_id,
        },
        "material_item": {
            "id": material_item.id if material_item else None,
            "work_title": material_item.work_title if material_item else None,
            "author": material_item.author if material_item else None,
            "source_path": material_item.source_path if material_item else None,
            "project_seq": material_item.project_seq if material_item else None,
        },
        "total_rated": total_rated,
        "total_chunks": total_chunks,
    }


class RatingSubmit(BaseModel):
    chunk_id: str
    material_item_id: str
    dimension_scores: dict[str, float] = {}
    skipped: bool = False
    skip_reason: str | None = None


@router.post("", status_code=201)
def submit_rating(
    project_id: str,
    body: RatingSubmit,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    rating = Rating(
        project_id=project_id,
        chunk_id=body.chunk_id,
        material_item_id=body.material_item_id,
        dimension_scores=body.dimension_scores,
        skipped=body.skipped,
        skip_reason=body.skip_reason,
    )
    SQLiteRatingStore(session).save(rating)
    session.commit()
    return _rating_response(rating)


@router.get("")
def list_ratings(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[dict]:
    _get_project_or_404(project_id, session)
    return [_rating_response(r) for r in SQLiteRatingStore(session).list_by_project(project_id)]
