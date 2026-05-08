from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text as _text
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
    total_chunks = chunk_store.count_by_project(proj.id) - skipped
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


_SORT_COLS: dict[str, str] = {
    "chunk_position": "c.position",
    "work_seq": "COALESCE(m.project_seq, 0)",
    "avg_score": "(SELECT AVG(j.value) FROM json_each(r.dimension_scores) j)",
    "is_ai": "r.is_ai",
}


@router.get("/counts")
def rating_counts(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    return SQLiteRatingStore(session).count_by_type(project_id)


@router.get("/rated-chunks")
def list_rated_chunks(
    project_id: str,
    work_seq: int | None = None,
    sort_by: str = "chunk_position",
    sort_dir: str = "asc",
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> dict:
    import json as _json

    _get_project_or_404(project_id, session)

    # Build safe sort column — never interpolate user input directly
    if sort_by in _SORT_COLS:
        sort_col = _SORT_COLS[sort_by]
    elif sort_by.startswith("dim:"):
        dim_name = sort_by[4:].replace('"', "")
        sort_col = f'json_extract(r.dimension_scores, \'$.\"{dim_name}\"\')'
    else:
        sort_col = "c.position"

    direction = "ASC" if sort_dir.lower() != "desc" else "DESC"

    work_filter = "AND m.project_seq = :work_seq" if work_seq is not None else ""

    base_where = f"""
        r.project_id = :pid AND r.skipped = 0
        AND (
            r.is_ai = 1
            OR NOT EXISTS (
                SELECT 1 FROM ratings r2
                WHERE r2.chunk_id = r.chunk_id
                  AND r2.project_id = :pid
                  AND r2.is_ai = 1
                  AND r2.skipped = 0
            )
        )
        AND NOT EXISTS (
            SELECT 1 FROM ratings r3
            WHERE r3.chunk_id = r.chunk_id
              AND r3.project_id = :pid
              AND r3.is_ai = r.is_ai
              AND r3.skipped = 0
              AND r3.rated_at > r.rated_at
        )
        {work_filter}
    """

    count_sql = _text(f"""
        SELECT COUNT(*)
        FROM ratings r
        JOIN chunks c ON c.id = r.chunk_id
        JOIN material_items m ON m.id = r.material_item_id
        WHERE {base_where}
    """)

    items_sql = _text(f"""
        SELECT
            r.id            AS rating_id,
            r.chunk_id,
            r.is_ai,
            r.dimension_scores,
            r.explanations,
            r.rated_at,
            c.position      AS chunk_position,
            c.content_is_str AS chunk_content_is_str,
            c.description   AS chunk_description,
            (SELECT COUNT(*) FROM chunks c2
             WHERE c2.material_item_id = c.material_item_id) AS chunk_count,
            m.id            AS material_item_id,
            m.project_seq   AS work_seq,
            m.work_title,
            m.author,
            EXISTS(
                SELECT 1 FROM ratings ra
                WHERE ra.chunk_id = r.chunk_id
                  AND ra.project_id = :pid
                  AND ra.is_ai = 0
                  AND ra.skipped = 0
            ) AS also_human_rated
        FROM ratings r
        JOIN chunks c ON c.id = r.chunk_id
        JOIN material_items m ON m.id = r.material_item_id
        WHERE {base_where}
        ORDER BY {sort_col} {direction}
        LIMIT :limit OFFSET :offset
    """)

    params: dict = {"pid": project_id, "limit": limit, "offset": offset}
    if work_seq is not None:
        params["work_seq"] = work_seq

    total: int = session.execute(count_sql, params).scalar_one()
    rows = session.execute(items_sql, params).fetchall()

    items = []
    for row in rows:
        dim_scores: dict = _json.loads(row.dimension_scores) if row.dimension_scores else {}
        explanations: dict = _json.loads(row.explanations) if row.explanations else {}
        avg_score = round(sum(dim_scores.values()) / len(dim_scores), 2) if dim_scores else None

        chunk_domain = "text" if row.chunk_content_is_str else "image"

        items.append({
            "rating_id": row.rating_id,
            "chunk_id": row.chunk_id,
            "chunk_position": row.chunk_position,
            "chunk_count": row.chunk_count,
            "chunk_content": None,
            "chunk_domain": chunk_domain,
            "chunk_description": row.chunk_description,
            "material_item_id": row.material_item_id,
            "work_seq": row.work_seq,
            "work_title": row.work_title,
            "author": row.author,
            "dimension_scores": dim_scores,
            "avg_score": avg_score,
            "is_ai": bool(row.is_ai),
            "also_human_rated": bool(row.also_human_rated) and bool(row.is_ai),
            "explanations": explanations,
            "rated_at": row.rated_at.isoformat() if hasattr(row.rated_at, "isoformat") else row.rated_at,
        })

    return {"total": total, "items": items}


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
