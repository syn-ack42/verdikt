from __future__ import annotations

import base64
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from verdikt.api.deps import get_auth_session, get_config, get_current_user, get_session
from verdikt.api.token_budget import check_token_budget, record_usage
from verdikt.core.models import DiscoveryRating, RatingDimension
from verdikt.core.user_models import AuthenticatedUser
from verdikt.inference.dimension_discoverer import DimensionDiscoverer
from verdikt.inference.resolver import resolve_llm_model
from verdikt.pipeline.selector import RatingSelector
from verdikt.storage.sqlite import (
    SQLiteChunkStore, SQLiteDiscoveryRatingStore, SQLiteMaterialStore, SQLiteProjectStore, SQLiteRatingStore,
)

router = APIRouter(prefix="/api/projects/{project_id}/discovery", tags=["discovery"])

_READY_LIKED = 5
_READY_DISLIKED = 5


def _get_project_or_404(project_id: str, session: Session):
    proj = SQLiteProjectStore(session).get(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


@router.get("/next")
def discovery_next(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Return the next chunk for discovery rating using cluster-diversity sampling."""
    proj = _get_project_or_404(project_id, session)
    chunk_store = SQLiteChunkStore(session)
    rating_store = SQLiteRatingStore(session)
    discovery_store = SQLiteDiscoveryRatingStore(session)
    mat_store = SQLiteMaterialStore(session)

    # Exclude chunks already discovery-rated; delegate to RatingSelector for cluster diversity
    already_rated = discovery_store.get_rated_chunk_ids(project_id)

    # Use a lightweight proxy RatingStore so the selector treats discovery-rated chunks as "rated"
    class _ProxyRatingStore:
        def get_human_rated_chunk_ids(self, pid: str) -> set[str]:
            return already_rated

        def cluster_stats(self, *a, **kw):  # not used by _next_diversity directly
            return {}

        def count_by_project(self, pid: str) -> int:
            return len(already_rated)

        def list_unconfirmed_ai(self, pid: str):
            return []

        def list_human_scores(self, pid: str) -> dict:
            return {}

    selector = RatingSelector(chunk_store, _ProxyRatingStore(), project=proj)  # type: ignore[arg-type]
    chunk = selector._next_diversity(project_id)  # noqa: SLF001

    if chunk is None:
        raise HTTPException(status_code=404, detail="no_chunks_available")

    material_item = mat_store.get(chunk.material_item_id)
    counts = discovery_store.counts(project_id)

    if isinstance(chunk.content, bytes):
        chunk_content = base64.b64encode(chunk.content).decode()
        chunk_domain = "image"
    else:
        chunk_content = chunk.content
        chunk_domain = "text"

    return {
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
        "total_discovery_rated": counts["total"],
        "liked": counts["liked"],
        "disliked": counts["disliked"],
    }


class DiscoveryRatingSubmit(BaseModel):
    chunk_id: str
    material_item_id: str
    preference: float   # -2 to +2; 0 treated as skip/neutral
    reason: str | None = None


@router.post("/ratings", status_code=201)
def submit_discovery_rating(
    project_id: str,
    body: DiscoveryRatingSubmit,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    store = SQLiteDiscoveryRatingStore(session)
    dr = DiscoveryRating(
        project_id=project_id,
        chunk_id=body.chunk_id,
        material_item_id=body.material_item_id,
        preference=max(-2.0, min(2.0, body.preference)),
        reason=body.reason or None,
    )
    store.save(dr)
    session.commit()
    counts = store.counts(project_id)
    return {
        "ok": True,
        "total": counts["total"],
        "liked": counts["liked"],
        "disliked": counts["disliked"],
        "ready": counts["liked"] >= _READY_LIKED and counts["disliked"] >= _READY_DISLIKED,
    }


@router.get("/status")
def discovery_status(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    counts = SQLiteDiscoveryRatingStore(session).counts(project_id)
    return {
        "total": counts["total"],
        "liked": counts["liked"],
        "disliked": counts["disliked"],
        "ready": counts["liked"] >= _READY_LIKED and counts["disliked"] >= _READY_DISLIKED,
    }


@router.post("/analyse/stream")
def analyse_stream(
    project_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> StreamingResponse:
    """SSE stream: describes each chunk then synthesises dimension proposals."""
    check_token_budget(user.id, auth_session)

    proj = _get_project_or_404(project_id, session)
    discovery_store = SQLiteDiscoveryRatingStore(session)
    chunk_store = SQLiteChunkStore(session)

    discovery_ratings = discovery_store.list_by_project(project_id)
    active = [dr for dr in discovery_ratings if abs(dr.preference) >= 0.5]
    if not active:
        raise HTTPException(status_code=422, detail="No non-neutral discovery ratings found")

    chunk_ids = {dr.chunk_id for dr in active}
    chunks_by_id = {c.id: c for c in chunk_store.list_by_project(project_id) if c.id in chunk_ids}

    config = get_config()
    ollama_base_url, llm_model = resolve_llm_model(proj, config)
    discoverer = DimensionDiscoverer(model=llm_model, base_url=ollama_base_url)

    # Copy data needed by the generator before session may close
    _project = proj
    _ratings = active
    _chunks = chunks_by_id
    _user_id = user.id
    _project_id = project_id
    _model = llm_model

    def event_stream():
        prompt_tokens = 0
        completion_tokens = 0

        active_ratings = _ratings
        total_active = len(active_ratings)
        descriptions: list[tuple[float, str]] = []

        for i, dr in enumerate(active_ratings):
            chunk = _chunks.get(dr.chunk_id)
            if chunk is None:
                continue
            try:
                qualities, pt, ct = discoverer._describe_chunk(chunk, dr, _project.domain)  # noqa: SLF001
                prompt_tokens += pt
                completion_tokens += ct
                if qualities:
                    descriptions.append((dr.preference, qualities))
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'progress', 'phase': 'describing', 'done': i + 1, 'total': total_active})}\n\n"

        yield f"data: {json.dumps({'type': 'progress', 'phase': 'synthesising', 'done': 0, 'total': 1})}\n\n"

        try:
            result, pt, ct = discoverer._extract_dimensions(descriptions, _project)  # noqa: SLF001
            prompt_tokens += pt
            completion_tokens += ct
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            return

        try:
            from sqlalchemy.orm import Session as _Session
            from verdikt.api.deps import get_auth_engine
            with _Session(get_auth_engine()) as _auth:
                record_usage(_user_id, _project_id, _model, "discovery_analyse", prompt_tokens, completion_tokens, _auth)
        except Exception:
            pass

        yield f"data: {json.dumps({'type': 'progress', 'phase': 'synthesising', 'done': 1, 'total': 1})}\n\n"
        yield f"data: {json.dumps({'type': 'complete', 'result': result.model_dump()})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class ApplyProposalBody(BaseModel):
    dimensions: list[dict]  # [{name, description, weight}]


@router.post("/apply")
def apply_proposal(
    project_id: str,
    body: ApplyProposalBody,
    session: Session = Depends(get_session),
) -> dict:
    """Apply the approved dimension proposal to the project."""
    from sqlalchemy import update as sql_update
    from verdikt.storage.orm import ProjectRow

    proj = _get_project_or_404(project_id, session)

    new_dims = []
    for d in body.dimensions:
        name = str(d.get("name", "")).strip()
        desc = str(d.get("description", "")).strip()
        if not name:
            continue
        weight = float(d.get("weight", 1.0))
        weight = max(0.1, min(5.0, weight))
        new_dims.append(RatingDimension(name=name, description=desc, weight=weight))

    if not new_dims:
        raise HTTPException(status_code=422, detail="No valid dimensions in proposal")

    session.execute(
        sql_update(ProjectRow)
        .where(ProjectRow.id == project_id)
        .values(rating_dimensions=json.dumps([d.model_dump() for d in new_dims]))
    )
    session.commit()

    proj.rating_dimensions = new_dims
    return {
        "id": proj.id,
        "name": proj.name,
        "rating_dimensions": [d.model_dump() for d in new_dims],
    }


@router.post("/reset")
def reset_discovery(
    project_id: str,
    session: Session = Depends(get_session),
) -> dict:
    _get_project_or_404(project_id, session)
    SQLiteDiscoveryRatingStore(session).delete_by_project(project_id)
    session.commit()
    return {"ok": True}
