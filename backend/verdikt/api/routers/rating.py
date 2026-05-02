from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_session
from verdikt.core.models import Rating
from verdikt.pipeline.selector import RatingSelector
from verdikt.storage.sqlite import (
    SQLiteChunkStore, SQLiteMaterialStore, SQLiteProfileStore, SQLiteProjectStore, SQLiteRatingStore,
)


def _compute_agreement(ai_scores: dict[str, float], user_scores: dict[str, float]) -> float:
    dims = set(ai_scores) & set(user_scores)
    if not dims:
        return 1.0
    return sum(1.0 - abs(ai_scores[d] - user_scores[d]) / 4.0 for d in dims) / len(dims)

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
        "is_ai": r.is_ai,
        "rated_at": r.rated_at.isoformat(),
    }


@router.get("/next")
def next_chunk(
    project_id: str,
    mode: str = "normal",
    session: Session = Depends(get_session),
) -> dict:
    proj = _get_project_or_404(project_id, session)
    chunk_store = SQLiteChunkStore(session)
    rating_store = SQLiteRatingStore(session)
    mat_store = SQLiteMaterialStore(session)

    confirm_ai = mode == "confirm_ai"
    selector = RatingSelector(chunk_store, rating_store, confirm_ai_mode=confirm_ai, project=proj)
    chunk = selector.next_chunk(proj.id)

    if chunk is None:
        detail = "no_ai_chunks" if confirm_ai else "No unrated chunks available"
        raise HTTPException(status_code=404, detail=detail)

    material_item = mat_store.get(chunk.material_item_id)
    skipped = rating_store.count_skipped(proj.id)
    total_chunks = len(chunk_store.list_by_project(proj.id)) - skipped
    rating_count = rating_store.count_by_project(proj.id)
    total_rated = rating_count - skipped
    confidence = min(1.0, rating_count / proj.crystallisation_threshold) if proj.crystallisation_threshold > 0 else 1.0

    import base64
    if isinstance(chunk.content, bytes):
        chunk_content = base64.b64encode(chunk.content).decode()
        chunk_domain = "image"
    else:
        chunk_content = chunk.content
        chunk_domain = "text"

    response: dict = {
        "chunk": {
            "id": chunk.id,
            "content": chunk_content,
            "domain": chunk_domain,
            "position": chunk.position,
            "cluster_id": chunk.cluster_id,
            "description": chunk.description,
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
        "confidence": round(confidence, 3),
    }

    if confirm_ai:
        ai_ratings = rating_store.list_unconfirmed_ai(proj.id)
        ai_rating = next((r for r in ai_ratings if r.chunk_id == chunk.id), None)
        response["prefilled_scores"] = ai_rating.dimension_scores if ai_rating else {}
        response["ai_rating_id"] = ai_rating.id if ai_rating else None
        response["ai_explanations"] = ai_rating.explanations if ai_rating else {}

    return response


class RatingSubmit(BaseModel):
    chunk_id: str
    material_item_id: str
    dimension_scores: dict[str, float] = {}
    skipped: bool = False
    skip_reason: str | None = None
    ai_rating_id: str | None = None  # set when confirming a background AI preview


@router.post("", status_code=201)
def submit_rating(
    project_id: str,
    body: RatingSubmit,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    rating_store = SQLiteRatingStore(session)

    if body.ai_rating_id and not body.skipped:
        # Confirm a background AI preview: update the AI rating to human-confirmed
        ai_rating = rating_store.get(body.ai_rating_id)
        if ai_rating is None or ai_rating.project_id != project_id:
            raise HTTPException(status_code=404, detail="AI rating not found")
        ai_scores = ai_rating.dimension_scores
        rating_store.update_scores(body.ai_rating_id, body.dimension_scores)
        agreement = _compute_agreement(ai_scores, body.dimension_scores)
        SQLiteProfileStore(session).increment_confidence(project_id, agreement)
        session.commit()
        return _rating_response(rating_store.get(body.ai_rating_id))

    rating = Rating(
        project_id=project_id,
        chunk_id=body.chunk_id,
        material_item_id=body.material_item_id,
        dimension_scores=body.dimension_scores,
        skipped=body.skipped,
        skip_reason=body.skip_reason,
    )
    rating_store.save(rating)
    session.commit()
    return _rating_response(rating)


@router.get("")
def list_ratings(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[dict]:
    _get_project_or_404(project_id, session)
    return [_rating_response(r) for r in SQLiteRatingStore(session).list_by_project(project_id)]


@router.get("/rated-chunks")
def list_rated_chunks(
    project_id: str,
    work_seq: int | None = None,
    session: Session = Depends(get_session),
) -> list[dict]:
    _get_project_or_404(project_id, session)
    rating_store = SQLiteRatingStore(session)
    chunk_store = SQLiteChunkStore(session)
    mat_store = SQLiteMaterialStore(session)

    all_ratings = [r for r in rating_store.list_by_project(project_id) if not r.skipped]

    if work_seq is not None:
        material = mat_store.get_by_seq(project_id, work_seq)
        if material is None:
            return []
        target_id = material.id
        all_ratings = [r for r in all_ratings if r.material_item_id == target_id]

    # Deduplicate: prefer human over AI for the same chunk
    best_by_chunk: dict = {}
    for r in all_ratings:
        existing = best_by_chunk.get(r.chunk_id)
        if existing is None or (existing.is_ai and not r.is_ai):
            best_by_chunk[r.chunk_id] = r

    # Track chunks that also have an AI rating (even when human wins)
    ai_rated_chunk_ids = {r.chunk_id for r in all_ratings if r.is_ai}

    # Cache material info and chunk counts to avoid N+1
    mat_cache: dict = {}
    chunk_count_cache: dict = {}

    result = []
    for r in best_by_chunk.values():
        mid = r.material_item_id
        if mid not in mat_cache:
            mat = mat_store.get(mid)
            mat_cache[mid] = mat
            if mat:
                chunk_count_cache[mid] = len(chunk_store.list_by_material(mid))
        mat = mat_cache.get(mid)
        chunk = chunk_store.get(r.chunk_id)
        if chunk is None:
            continue
        avg_score = (
            sum(r.dimension_scores.values()) / len(r.dimension_scores)
            if r.dimension_scores else None
        )
        import base64 as _b64
        if isinstance(chunk.content, bytes):
            chunk_content = _b64.b64encode(chunk.content).decode()
            chunk_domain = "image"
        else:
            chunk_content = chunk.content
            chunk_domain = "text"
        result.append({
            "rating_id": r.id,
            "chunk_id": r.chunk_id,
            "chunk_position": chunk.position,
            "chunk_count": chunk_count_cache.get(mid, 0),
            "chunk_content": chunk_content,
            "chunk_domain": chunk_domain,
            "chunk_description": chunk.description,
            "material_item_id": mid,
            "work_seq": mat.project_seq if mat else None,
            "work_title": mat.work_title if mat else None,
            "author": mat.author if mat else None,
            "dimension_scores": r.dimension_scores,
            "avg_score": round(avg_score, 2) if avg_score is not None else None,
            "is_ai": r.is_ai,
            "also_ai_rated": (not r.is_ai) and (r.chunk_id in ai_rated_chunk_ids),
            "explanations": r.explanations,
            "rated_at": r.rated_at.isoformat(),
        })

    result.sort(key=lambda x: (x["work_seq"] or 0, x["chunk_position"]))
    return result


class RatingUpdate(BaseModel):
    dimension_scores: dict[str, float]


@router.put("/{rating_id}")
def update_rating(
    project_id: str,
    rating_id: str,
    body: RatingUpdate,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    rating_store = SQLiteRatingStore(session)
    rating = rating_store.get(rating_id)
    if rating is None or rating.project_id != project_id:
        raise HTTPException(status_code=404, detail="Rating not found")
    # Capture AI scores before confirming, for confidence tracking
    ai_scores = rating.dimension_scores if rating.is_ai else None
    rating_store.update_scores(rating_id, body.dimension_scores)
    if ai_scores:
        agreement = _compute_agreement(ai_scores, body.dimension_scores)
        SQLiteProfileStore(session).increment_confidence(project_id, agreement)
    session.commit()
    updated = rating_store.get(rating_id)
    return _rating_response(updated)
